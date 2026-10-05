"""Filesystem tools. Every path is checked against the shared folders, then opened through a
directory descriptor with O_NOFOLLOW so a symlink swapped in after the check cannot redirect it."""
from __future__ import annotations

import asyncio
import contextlib
import difflib
import fnmatch
import json
import os
import secrets
import shutil
import stat
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from lilly.domain.errors import PolicyDenied, ToolError, ValidationFailed
from lilly.domain.labels import Label, Verdict
from lilly.domain.policy import PathScope
from lilly.domain.ports import ToolContext, ToolResult
from lilly.domain.prompts import PROTECTED_PATH_REASON
from lilly.domain.text import extract_json
from lilly.store import undo as undo_store
from lilly.store.db import Database
from lilly.store.undo import hash_content
from lilly.tools.base import Tool, bool_arg, int_arg, resolve_in_scope, str_arg

DEFAULT_READ_BYTES = 256 * 1024
MAX_READ_BYTES = 2 * 1024 * 1024
MAX_WRITE_BYTES = 5 * 1024 * 1024
MAX_SEARCH_FILE_BYTES = 256 * 1024
MAX_SEARCH_FILES = 20_000
MAX_MOVES = 500
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv"})
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _out(payload: object, label: Label) -> ToolResult:
    return ToolResult(json.dumps(payload, indent=1), label, False)


class _FsTool(Tool):
    def __init__(self, scope: PathScope,
                 protected_globs: tuple[str, ...] | Callable[[], tuple[str, ...]] = ()) -> None:
        self._scope = scope
        self._protected_globs = protected_globs

    def _is_protected(self, target: Path | str) -> bool:
        globs = self._protected_globs() if callable(self._protected_globs) else self._protected_globs
        if not globs:
            return False
        p = Path(target)
        rel_p: Path | None = None
        for root in self._scope.roots:
            try:
                rel_p = p.relative_to(root)
                break
            except ValueError:
                pass

        target_p = rel_p if rel_p is not None else p
        name = target_p.name
        str_path = str(target_p)
        for pattern in globs:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str_path, pattern):
                return True
            for part in target_p.parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
        return False

    def _path(self, args: Mapping[str, object], key: str = "path") -> Path:
        return resolve_in_scope(str_arg(args, key), self._scope)


class FsReadTool(_FsTool):
    name = "fs.read"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        path = self._path(args)
        has_range = "offset" in args or "limit" in args
        offset_val = int_arg(args, "offset", 1, lo=1, hi=10_000_000) if "offset" in args else (1 if has_range else None)
        limit_val = int_arg(args, "limit", 1000, lo=1, hi=10_000_000) if "limit" in args else None
        max_bytes = int_arg(args, "max_bytes", DEFAULT_READ_BYTES, lo=1, hi=MAX_READ_BYTES)
        return await asyncio.to_thread(self._read, path, max_bytes, offset_val, limit_val)

    @staticmethod
    def _read(path: Path, max_bytes: int, offset: int | None = None, limit: int | None = None) -> ToolResult:
        try:
            dir_fd = os.open(path.parent, _DIR_FLAGS)
        except OSError as exc:
            raise ToolError(f"cannot open folder: {exc.strerror}") from exc
        try:
            # O_NONBLOCK so a FIFO cannot hang us; only regular files are accepted below.
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except OSError as exc:
            raise ToolError(f"cannot open file: {exc.strerror}") from exc
        finally:
            os.close(dir_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ToolError("not a regular file")
            chunks: list[bytes] = []
            remaining = MAX_READ_BYTES if (offset is not None or limit is not None) else max_bytes
            while remaining > 0:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            os.close(fd)
        data = b"".join(chunks)
        if _is_binary(data[:8192]):
            raise ToolError("this looks like a binary file, not text")
        text = data.decode("utf-8", errors="replace")

        if offset is not None or limit is not None:
            lines = text.splitlines()
            start = offset or 1
            if start > len(lines):
                return ToolResult(f"[file has {len(lines)} lines; offset {start} is beyond end]", Label.PERSONAL, False)
            end = (start - 1 + limit) if limit is not None else None
            selected = lines[start - 1 : end]
            numbered = "\n".join(f"{start + i}: {line}" for i, line in enumerate(selected))
            return ToolResult(numbered, Label.PERSONAL, False)

        if info.st_size > max_bytes:
            text += f"\n[truncated: showing the first {max_bytes} of {info.st_size} bytes]"
        return ToolResult(text, Label.PERSONAL, False)


class FsEditTool(_FsTool):
    name = "fs.edit"

    def __init__(
        self,
        scope: PathScope,
        db: Database | None = None,
        protected_globs: tuple[str, ...] | Callable[[], tuple[str, ...]] = (),
    ) -> None:
        super().__init__(scope, protected_globs)
        self._db = db

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        path = self._path(args)
        if self._is_protected(path):
            raise PolicyDenied(PROTECTED_PATH_REASON)
        old_text = str_arg(args, "old")
        new_text = str_arg(args, "new")
        replace_all = bool_arg(args, "replace_all")

        res, undo_tuple = await asyncio.to_thread(self._edit, path, old_text, new_text, replace_all)
        if self._db is not None and undo_tuple is not None:
            orig_content, before_h, after_h = undo_tuple
            now = time.time()
            await self._db.write(
                lambda con: undo_store.record_undo(
                    con,
                    task_id=ctx.task_id,
                    step_id=ctx.step_id,
                    path=str(path),
                    original_content=orig_content,
                    before_hash=before_h,
                    after_hash=after_h,
                    now=now,
                )
            )
        return res

    def _edit(
        self,
        path: Path,
        old_text: str,
        new_text: str,
        replace_all: bool,
    ) -> tuple[ToolResult, tuple[str, str, str] | None]:
        if not path.exists():
            raise ToolError(f"file not found: {path}")
        try:
            dir_fd = os.open(path.parent, _DIR_FLAGS)
        except OSError as exc:
            raise ToolError(f"cannot open folder: {exc.strerror}") from exc
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except OSError as exc:
            raise ToolError(f"cannot open file: {exc.strerror}") from exc
        finally:
            os.close(dir_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ToolError("not a regular file")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(len(c) for c in chunks) > MAX_WRITE_BYTES:
                    raise ToolError("file exceeds maximum editable size")
            raw_bytes = b"".join(chunks)
        finally:
            os.close(fd)

        if _is_binary(raw_bytes[:8192]):
            raise ToolError("this looks like a binary file, not text")
        original_text = raw_bytes.decode("utf-8", errors="replace")

        count = original_text.count(old_text)
        if count == 0:
            raise ToolError(f"old text not found in {path}")
        if count > 1 and not replace_all:
            raise ToolError(
                f"old text appears {count} times in {path}; add surrounding lines to make it unique or set replace_all"
            )

        if replace_all:
            edited_text = original_text.replace(old_text, new_text)
        else:
            edited_text = original_text.replace(old_text, new_text, 1)

        # Preserve CRLF newline style if present
        if "\r\n" in original_text and "\r\n" not in edited_text:
            edited_text = edited_text.replace("\n", "\r\n")

        mode = stat.S_IMODE(info.st_mode)

        temp_name = f".tmp_edit_{secrets.token_hex(8)}"
        temp_path = path.parent / temp_name
        try:
            with open(temp_path, "w", encoding="utf-8", newline="") as f:
                f.write(edited_text)
            os.chmod(temp_path, mode)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                with contextlib.suppress(OSError):
                    temp_path.unlink()

        before_h = hash_content(original_text)
        after_h = hash_content(edited_text)

        diff = "".join(
            difflib.unified_diff(
                original_text.splitlines(keepends=True),
                edited_text.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )
        msg = f"Successfully edited {path}.\n{diff}" if diff else f"Successfully edited {path}."
        return ToolResult(msg, Label.PERSONAL, False), (original_text, before_h, after_h)


class FsListTool(_FsTool):
    name = "fs.list"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        path = self._path(args)
        limit = int_arg(args, "max_entries", 500, lo=1, hi=5000)
        return await asyncio.to_thread(self._list, path, limit)

    @staticmethod
    def _list(path: Path, limit: int) -> ToolResult:
        entries: list[dict[str, Any]] = []
        truncated = False
        try:
            with os.scandir(path) as it:
                for entry in sorted(it, key=lambda e: e.name.lower()):
                    if len(entries) >= limit:
                        truncated = True
                        break
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue  # vanished or unreadable: skip it rather than fail the whole listing
                    kind = "link" if entry.is_symlink() else "dir" if entry.is_dir(follow_symlinks=False) else "file"
                    entries.append({"name": entry.name, "type": kind,
                                    "size": info.st_size if kind == "file" else None, "modified": _iso(info.st_mtime)})
        except (NotADirectoryError, FileNotFoundError, PermissionError) as exc:
            raise ToolError(f"cannot list folder: {exc.strerror}") from exc
        return _out({"path": str(path), "entries": entries, "truncated": truncated}, Label.PERSONAL)


class FsSearchTool(_FsTool):
    name = "fs.search"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        root = self._path(args)
        query = str_arg(args, "query", max_len=200).lower()
        limit = int_arg(args, "max_results", 50, lo=1, hi=500)
        return await asyncio.to_thread(self._search, root, query, limit, ctx.cancelled, self._scope.allows)

    @staticmethod
    def _search(root: Path, query: str, limit: int, cancelled: Any, allows: Callable[[str], bool]) -> ToolResult:
        hits: list[dict[str, str]] = []
        scanned = 0
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and allows(os.path.join(dirpath, d))]
            for name in filenames:
                if cancelled():
                    raise ToolError("cancelled")
                if len(hits) >= limit or scanned >= MAX_SEARCH_FILES:
                    truncated = True
                    break
                full = os.path.join(dirpath, name)
                try:
                    info = os.lstat(full)  # never follow a symlink out of the shared folder
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode) or not allows(full):
                    continue  # not a plain file, or inside a folder Lilly must never read
                scanned += 1
                if query in name.lower():
                    hits.append({"path": full, "match": "name"})
                    continue
                if info.st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                try:
                    with open(full, "rb") as f:
                        data = f.read(MAX_SEARCH_FILE_BYTES)
                except OSError:
                    continue
                if _is_binary(data[:8192]):
                    continue
                text = data.decode("utf-8", errors="ignore")
                idx = text.lower().find(query)
                if idx >= 0:
                    start = max(0, idx - 60)
                    hits.append({"path": full, "match": "text", "snippet": " ".join(text[start:idx + 100].split())})
            if truncated:
                break
        return _out({"query": query, "hits": hits, "files_scanned": scanned, "truncated": truncated}, Label.PERSONAL)


class FsWriteTool(_FsTool):
    name = "fs.write"

    def review(self, args: Mapping[str, object], task_id: str) -> tuple[Verdict, str]:
        path_str = str(args.get("path", ""))
        if self._is_protected(path_str):
            return Verdict.NEEDS_APPROVAL, PROTECTED_PATH_REASON
        return Verdict.ALLOW, "ok"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        path = self._path(args)
        content = args.get("content", "")
        if not isinstance(content, str):
            raise ValidationFailed("'content' must be text")
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise ValidationFailed("content is too large to write")
        overwrite = bool_arg(args, "overwrite")
        return await asyncio.to_thread(self._write, path, data, overwrite)

    @staticmethod
    def _write(path: Path, data: bytes, overwrite: bool) -> ToolResult:
        try:
            dir_fd = os.open(path.parent, _DIR_FLAGS)
        except OSError as exc:
            raise ToolError(f"the folder does not exist or cannot be opened: {exc.strerror}") from exc
        tmp = f".lilly-{secrets.token_hex(6)}.tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o666, dir_fd=dir_fd)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                if overwrite:
                    os.replace(tmp, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
                else:
                    try:
                        os.link(tmp, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)  # fails if it exists
                    except FileExistsError:
                        raise ToolError("a file with that name already exists; set overwrite to replace it") from None
                    os.unlink(tmp, dir_fd=dir_fd)
            except BaseException:
                try:
                    os.unlink(tmp, dir_fd=dir_fd)
                except OSError:
                    pass
                raise
        except OSError as exc:
            raise ToolError(f"cannot write file: {exc.strerror}") from exc
        finally:
            os.close(dir_fd)
        return ToolResult(f"Wrote {len(data)} bytes to {path}", Label.PUBLIC, False)


class FsApplyMovesTool(_FsTool):
    name = "fs.apply_moves"

    def review(self, args: Mapping[str, object], task_id: str) -> tuple[Verdict, str]:
        raw = args.get("moves")
        if isinstance(raw, str):
            with contextlib.suppress(Exception):
                raw = extract_json(raw)
        if isinstance(raw, dict) and isinstance(raw.get("moves"), list):
            raw = raw["moves"]
        if isinstance(raw, list):
            for m in raw:
                if isinstance(m, dict):
                    if self._is_protected(str(m.get("from", ""))) or self._is_protected(str(m.get("to", ""))):
                        return Verdict.NEEDS_APPROVAL, PROTECTED_PATH_REASON
        return Verdict.ALLOW, "ok"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        root = self._path(args, "root")
        raw = args.get("moves")
        if isinstance(raw, str):
            try:
                raw = extract_json(raw)
            except ValueError as exc:
                raise ValidationFailed("'moves' is not valid JSON") from exc
        if isinstance(raw, dict) and isinstance(raw.get("moves"), list):
            raw = raw["moves"]
        if not isinstance(raw, list) or not raw:
            raise ValidationFailed("'moves' must be a non-empty list of {from, to}")
        if len(raw) > MAX_MOVES:
            raise ValidationFailed(f"at most {MAX_MOVES} moves at a time")
        return await asyncio.to_thread(self._apply, root, raw, self._scope.denies)

    @staticmethod
    def _locate(root: Path, rel: object, what: str, denied: Callable[[Path], bool]) -> Path:
        """root/rel with the parent folder resolved but the final name left alone, so moving a
        symlink moves the link itself and never what it points to."""
        if not isinstance(rel, str) or not rel.strip() or os.path.isabs(rel) or "\x00" in rel:
            raise ValidationFailed(f"{what} must be a path relative to the folder")
        joined = root / rel
        parent = Path(os.path.realpath(joined.parent))
        if parent != root and root not in parent.parents:
            raise PolicyDenied(f"{what} {rel!r} leaves the folder")
        if joined.name in ("", ".", ".."):
            raise ValidationFailed(f"{what} {rel!r} is not a file name")
        located = parent / joined.name
        if denied(located):
            raise PolicyDenied(f"{what} {rel!r} is in a folder Lilly must not touch")
        return located

    @classmethod
    def _apply(cls, root: Path, raw: list[Any], denied: Callable[[Path], bool]) -> ToolResult:
        plan: list[tuple[Path, Path]] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValidationFailed(f"move {i + 1} is not an object")
            src = cls._locate(root, item.get("from", item.get("src")), "source", denied)
            dst = cls._locate(root, item.get("to", item.get("dst")), "destination", denied)
            plan.append((src, dst))
        sources = {s for s, _ in plan}
        destinations = [d for _, d in plan]
        if len(set(destinations)) != len(destinations):
            raise ValidationFailed("two moves have the same destination")
        for src, dst in plan:
            if not os.path.lexists(src):
                raise ToolError(f"{src.name} does not exist")
            if os.path.lexists(dst) or dst in sources:  # also catches a move onto itself
                raise ToolError(f"refusing to overwrite {dst.name}")
        done: list[tuple[Path, Path]] = []
        try:
            for src, dst in plan:
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.rename(src, dst)
                done.append((src, dst))
        except OSError as exc:
            for src, dst in reversed(done):
                try:
                    os.rename(dst, src)
                except OSError:
                    pass
            raise ToolError(f"a move failed ({exc.strerror}); everything already moved was put back") from exc
        undo = [{"from": str(d.relative_to(root)), "to": str(s.relative_to(root))} for s, d in done]
        return _out({"moved": len(done), "undo": undo}, Label.PUBLIC)


class FsTrashTool(_FsTool):
    name = "fs.trash"

    def review(self, args: Mapping[str, object], task_id: str) -> tuple[Verdict, str]:
        path_str = str(args.get("path", ""))
        if self._is_protected(path_str):
            return Verdict.NEEDS_APPROVAL, PROTECTED_PATH_REASON
        return Verdict.ALLOW, "ok"

    async def run(self, args: Mapping[str, object], ctx: ToolContext) -> ToolResult:
        path = self._path(args)
        if path in self._scope.roots:
            raise PolicyDenied("a shared folder itself cannot be trashed")
        return await asyncio.to_thread(self._trash, path)

    @staticmethod
    def _trash(path: Path) -> ToolResult:
        if not os.path.lexists(path):
            raise ToolError("that path does not exist")
        home = Path.home()
        mac = home / ".Trash"
        if mac.is_dir():
            files, info = mac, None
        else:  # freedesktop.org Trash, so a file manager can restore it
            base = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "Trash"
            files, info = base / "files", base / "info"
            files.mkdir(parents=True, exist_ok=True)
            info.mkdir(parents=True, exist_ok=True)
        target, n = files / path.name, 1
        while os.path.lexists(target):
            target = files / f"{path.stem}-{n}{path.suffix}"
            n += 1
        try:
            shutil.move(str(path), str(target))
        except OSError as exc:
            raise ToolError(f"could not move to the Trash: {exc.strerror}") from exc
        if info is not None:
            (info / f"{target.name}.trashinfo").write_text(
                f"[Trash Info]\nPath={quote(str(path))}\nDeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
        return ToolResult(f"Moved {path.name} to the Trash", Label.PUBLIC, False)

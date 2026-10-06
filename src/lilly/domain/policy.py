"""The policy kernel: path scope and decide(). Pure, deterministic, no model, no network."""
from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable
from pathlib import Path

from lilly.domain.labels import ApprovalMode, Label, Mode, Risk, TaskCtx, ToolCall, Verdict


def _names(p: Path) -> tuple[str, ...]:
    """A path's parts as a file system that ignores case and the form of accents (macOS, Windows) sees them: there
    `.LILLY` is Lilly's own `.lilly`, and realpath does not say so."""
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in p.parts)


def _inside(inner: tuple[str, ...], outer: tuple[str, ...]) -> bool:
    return inner[:len(outer)] == outer


class PathScope:
    """Granted roots. realpath defeats '..' and symlink escapes; denied folders match under any spelling."""

    def __init__(self, roots: Iterable[str], deny: Iterable[str] = ()):
        self._roots = tuple(Path(os.path.realpath(os.path.expanduser(r))) for r in roots)
        self._deny = tuple(_names(Path(os.path.realpath(os.path.expanduser(d)))) for d in deny)

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    def allows(self, path: str) -> bool:
        if not path or "\x00" in path:
            return False
        try:
            p = Path(os.path.realpath(os.path.expanduser(path)))
        except (OSError, ValueError):
            return False
        if self.denies(p):
            return False  # for example Lilly's own data folder, even when it sits inside a shared folder
        return any(p == r or r in p.parents for r in self._roots)

    def shields(self, resolved: Path) -> bool:
        """Whether an already-resolved folder contains a denied folder (so sharing it would share that too)."""
        return any(_inside(d, _names(resolved)) for d in self._deny)

    def denies(self, resolved: Path) -> bool:
        """Whether an already-resolved path is, or is inside, a denied folder."""
        return any(_inside(_names(resolved), d) for d in self._deny)


def decide(call: ToolCall, ctx: TaskCtx, scope: PathScope) -> tuple[Verdict, str]:
    """Pure policy. Most restrictive matching rule wins.

    The floor applies in every mode: forbidden tools, computer control (always asks), credentials never shown to an
    agent, nothing secret leaves, sending out private data after reading untrusted
    content needs approval, and paths stay inside granted roots.

    Rule of Two (Meta, 2025): a session should not combine untrusted input, private
    data and the power to change state without a human in the loop. The floor
    therefore asks whenever a task that has read untrusted content tries to change
    anything (R1+), whether or not it holds private data: a poisoned web page must not
    be able to write a file or plant a memory unattended."""
    out: list[tuple[Verdict, str]] = []
    openm, locked = ctx.mode is Mode.OPEN, ctx.mode is Mode.LOCKED
    if call.risk is Risk.R3:
        out.append((Verdict.DENY, "forbidden tool"))
    if call.confirm:
        out.append((Verdict.NEEDS_APPROVAL, "always needs your approval, in every mode"))
    if call.risk is Risk.R1 and not openm and ctx.approval_mode is not ApprovalMode.AUTO:
        out.append((Verdict.NEEDS_APPROVAL, "changes your files or data"))
    if call.risk is Risk.R2 and not openm and ctx.approval_mode is not ApprovalMode.AUTO:
        out.append((Verdict.NEEDS_APPROVAL, "external or irreversible"))
    if ctx.tainted and call.risk is Risk.R2:
        out.append((Verdict.NEEDS_APPROVAL, "irreversible action after untrusted content"))
    if ctx.tainted and call.risk >= Risk.R1:
        out.append((Verdict.NEEDS_APPROVAL, "state change after reading untrusted content"))
    if call.reads_label is Label.SECRET:
        out.append((Verdict.DENY, "credentials are never shown to an agent"))
    elif call.reads_label is Label.PERSONAL:
        if locked:
            out.append((Verdict.DENY, "this agent has no private access"))
        elif not openm:
            out.append((Verdict.NEEDS_APPROVAL, "agent asks before reading private data"))
    if call.egress and ctx.label is Label.SECRET:
        out.append((Verdict.DENY, "secret data may not leave the device"))
    if call.egress and locked and ctx.label > Label.PUBLIC:
        out.append((Verdict.DENY, "this agent may not send private data"))
    if call.egress and ctx.tainted and ctx.label >= Label.PERSONAL:
        out.append((Verdict.NEEDS_APPROVAL, "private data could leave after reading untrusted content"))
    if call.egress and ctx.label is Label.PERSONAL and not openm:
        out.append((Verdict.NEEDS_APPROVAL, "personal data leaving the device"))
    if any(not scope.allows(p) for p in call.paths):
        out.append((Verdict.DENY, "path outside granted roots"))
    verdict = max(out, key=lambda r: r[0]) if out else (Verdict.ALLOW, "ok")
    if verdict[0] is Verdict.NEEDS_APPROVAL and ctx.approval_mode is ApprovalMode.OFF:
        return Verdict.DENY, "approval mode is OFF"
    return verdict

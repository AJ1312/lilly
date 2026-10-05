"""The Laya installer: it keeps a file only when it is exactly the reviewed one, and leaves nothing half done."""
from __future__ import annotations

import hashlib
import io
import subprocess
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from lilly.decide import laya_install as li
from lilly.decide.laya_pins import DOWNLOAD_BYTES, FILES, LAYA_VERSION, REVISION, WEIGHTS, PinnedFile


def pin(path: str, data: bytes, *, strong: bool = False) -> PinnedFile:
    git = hashlib.sha1(f"blob {len(data)}\0".encode() + data, usedforsecurity=False).hexdigest()
    return PinnedFile(path, len(data), git, hashlib.sha256(data).hexdigest() if strong else None)


class Reader(io.BytesIO):
    def __enter__(self) -> Reader:
        return self


def serving(contents: dict[str, bytes], seen: list[str] | None = None) -> Any:
    def opener(url: str) -> Reader:
        if seen is not None:
            seen.append(url)
        name = url.split(f"/resolve/{REVISION}/")[1]
        if name not in contents:
            raise urllib.error.URLError("not found")
        return Reader(contents[name])
    return opener


def fake_run(fail_pip: bool = False, versions: dict[str, str] | None = None, calls: list[list[str]] | None = None) -> Any:
    """A stand-in for subprocess.run. `versions` maps a python path to what it reports ("3 12"); others report 3.12."""
    def run(cmd: list[str], **kw: Any) -> Any:
        if calls is not None:
            calls.append(cmd)
        if cmd[1] == "-c":
            return SimpleNamespace(returncode=0, stdout=(versions or {}).get(cmd[0], "3 12") + "\n", stderr="")
        if cmd[1:3] == ["-m", "venv"]:
            py = Path(cmd[3]) / "bin" / "python"
            py.parent.mkdir(parents=True)
            py.write_text("")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        assert "--only-binary=:all:" in cmd and f"laya=={LAYA_VERSION}" in cmd
        return SimpleNamespace(returncode=1 if fail_pip else 0, stdout="", stderr="ERROR: no matching distribution")
    return run


DATA = {"a/one.json": b'{"x": 1}', WEIGHTS: b"weights" * 1000}
PINS = (pin("a/one.json", DATA["a/one.json"]), pin(WEIGHTS, DATA[WEIGHTS], strong=True))


def test_the_reviewed_pins_are_complete_and_safe() -> None:
    assert len(REVISION) == 40 and all(c in "0123456789abcdef" for c in REVISION)
    assert len({f.path for f in FILES}) == len(FILES) and DOWNLOAD_BYTES == sum(f.size for f in FILES)
    weights = next(f for f in FILES if f.path == WEIGHTS)
    assert weights.sha256 and len(weights.sha256) == 64 and weights.path.endswith(".safetensors")
    assert all(len(f.git_blob) == 40 and not f.path.endswith((".bin", ".pt", ".pkl", ".py")) for f in FILES)


def test_a_good_install_downloads_checks_and_marks_the_add_on_installed(tmp_path: Path) -> None:
    addon, seen = tmp_path / "laya", []
    li.install(addon, lambda _: None, opener=serving(DATA, seen), run=fake_run(), files=PINS)
    assert li.is_installed(addon)
    assert (li.model_dir(addon) / WEIGHTS).read_bytes() == DATA[WEIGHTS]
    assert all(u.startswith(f"https://huggingface.co/convaiinnovations/laya-typed-decisions/resolve/{REVISION}/")
               for u in seen)
    assert not list(addon.rglob("*.part"))


def test_a_second_install_does_not_download_files_it_already_has(tmp_path: Path) -> None:
    addon, seen = tmp_path / "laya", []
    li.install(addon, lambda _: None, opener=serving(DATA), run=fake_run(), files=PINS)
    li.install(addon, lambda _: None, opener=serving(DATA, seen), run=fake_run(), files=PINS)
    assert seen == []


def test_a_file_that_is_not_the_reviewed_one_is_refused_and_nothing_is_kept(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    tampered = {**DATA, "a/one.json": b'{"x": 2}'}                 # same size, different content
    with pytest.raises(li.LayaInstallError, match="not the reviewed file"):
        li.install(addon, lambda _: None, opener=serving(tampered), run=fake_run(), files=PINS)
    assert not li.is_installed(addon) and not (li.model_dir(addon) / "a/one.json").exists()
    assert not list(addon.rglob("*.part"))


def test_a_wrong_sha256_shows_the_hash_that_was_seen(tmp_path: Path) -> None:
    wrong = pin(WEIGHTS, DATA[WEIGHTS])                            # git id right, then a sha256 that is not
    bad = PinnedFile(wrong.path, wrong.size, wrong.git_blob, "0" * 64)
    with pytest.raises(li.LayaInstallError, match=hashlib.sha256(DATA[WEIGHTS]).hexdigest()):
        li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA), run=fake_run(), files=(bad,))


@pytest.mark.parametrize("served,message", [(b"x" * 5, "ended early"), (b"y" * 99999, "larger than")])
def test_a_short_or_oversized_download_is_refused(tmp_path: Path, served: bytes, message: str) -> None:
    with pytest.raises(li.LayaInstallError, match=message):
        li.install(tmp_path / "laya", lambda _: None, opener=serving({"a/one.json": served}), run=fake_run(),
                   files=(PINS[0],))


def test_a_network_failure_is_a_plain_message(tmp_path: Path) -> None:
    with pytest.raises(li.LayaInstallError, match="could not download a/one.json"):
        li.install(tmp_path / "laya", lambda _: None, opener=serving({}), run=fake_run(), files=(PINS[0],))


def test_when_the_packages_cannot_be_installed_nothing_is_marked_installed(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    with pytest.raises(li.LayaInstallError, match="pip could not install Laya.*no matching distribution"):
        li.install(addon, lambda _: None, opener=serving(DATA), run=fake_run(fail_pip=True), files=PINS)
    assert not li.is_installed(addon)


def test_a_failed_environment_is_reported(tmp_path: Path) -> None:
    def run(cmd: list[str], **kw: Any) -> Any:
        if cmd[1] == "-c":
            return SimpleNamespace(returncode=0, stdout="3 12\n", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="ensurepip is missing")
    with pytest.raises(li.LayaInstallError, match="could not create the environment"):
        li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA), run=run, files=PINS)


def test_too_little_disk_space_stops_before_anything_is_downloaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(li.shutil, "disk_usage", lambda p: SimpleNamespace(free=10))
    with pytest.raises(li.LayaInstallError, match="not enough free disk space"):
        li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA), run=fake_run(), files=PINS)


def test_the_marker_must_match_the_pinned_versions(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    li.install(addon, lambda _: None, opener=serving(DATA), run=fake_run(), files=PINS)
    (addon / li.MARKER).write_text('{"revision": "other", "laya": "0.0.1"}')
    assert not li.is_installed(addon)
    (addon / li.MARKER).write_text("not json")
    assert not li.is_installed(addon)


def test_remove_deletes_everything_and_says_when_there_was_nothing(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    li.install(addon, lambda _: None, opener=serving(DATA), run=fake_run(), files=PINS)
    assert li.remove(addon) and not addon.exists() and not li.remove(addon)


def test_redirects_may_only_go_to_https() -> None:
    handler = li._HttpsOnly()
    req = SimpleNamespace(full_url="https://huggingface.co/x", get_method=lambda: "GET", data=None, headers={},
                          origin_req_host="h", unverifiable=False)
    with pytest.raises(urllib.error.URLError, match="non-https"):
        handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example/model")   # type: ignore[arg-type]


def test_the_real_opener_is_built_for_the_pinned_host(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class Fake:
        def open(self, request: Any, timeout: float) -> str:
            captured["url"], captured["timeout"] = request.full_url, timeout
            return "response"

    monkeypatch.setattr(li.urllib.request, "build_opener", lambda *h: Fake())
    assert li._open("https://huggingface.co/a") == "response" and captured["timeout"] == li.READ_TIMEOUT_S


def test_a_real_pip_failure_is_read_from_a_real_process(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    py = li.python_of(addon)
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
    py.chmod(0o755)
    with pytest.raises(li.LayaInstallError, match="boom"):
        li._pip(addon, subprocess.run, APPLE)


INTEL = li.Host("darwin", "x86_64")
APPLE = li.Host("darwin", "arm64")


def test_an_intel_mac_with_only_a_new_python_is_refused_before_anything_is_downloaded(tmp_path: Path) -> None:
    seen: list[str] = []
    with pytest.raises(li.LayaInstallError, match="Python 3.12"):
        li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA, seen), files=PINS, host=INTEL,
                   run=fake_run(versions={"/usr/bin/new": "3 13"}), base_python="/usr/bin/new", which=lambda _: None)
    assert seen == [] and not (tmp_path / "laya" / li.MARKER).exists()


def test_an_intel_mac_uses_an_older_python_it_finds_and_holds_the_old_pytorch_packages(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA), files=PINS, host=INTEL,
               run=fake_run(versions={"/usr/bin/new": "3 13", "/opt/py312": "3 12"}, calls=calls),
               base_python="/usr/bin/new", which=lambda n: "/opt/py312" if n == "python3.12" else None)
    made = next(c for c in calls if c[1:3] == ["-m", "venv"])
    pip = next(c for c in calls if "pip" in c)
    assert made[0] == "/opt/py312"
    assert "numpy<2" in pip and "transformers>=4.48,<5" in pip and li.is_installed(tmp_path / "laya")


def test_other_computers_get_no_extra_pins_and_may_use_a_new_python(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA), files=PINS, host=APPLE,
               run=fake_run(versions={"/usr/bin/new": "3 13"}, calls=calls), base_python="/usr/bin/new")
    pip = next(c for c in calls if "pip" in c)
    assert pip[-1] == f"laya=={LAYA_VERSION}"


def test_a_python_that_is_too_old_for_laya_is_refused_anywhere(tmp_path: Path) -> None:
    with pytest.raises(li.LayaInstallError, match="3.10"):
        li.install(tmp_path / "laya", lambda _: None, opener=serving(DATA), files=PINS, host=APPLE,
                   run=fake_run(versions={"/usr/bin/old": "3 9"}), base_python="/usr/bin/old", which=lambda _: None)


def test_an_environment_made_by_an_unsuitable_python_is_rebuilt(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    bad = addon / "venv" / "bin" / "python"
    bad.parent.mkdir(parents=True)
    bad.write_text("")
    calls: list[list[str]] = []
    li.install(addon, lambda _: None, opener=serving(DATA), files=PINS, host=INTEL,
               run=fake_run(versions={str(bad): "3 13"}, calls=calls), base_python="/usr/bin/ok")
    assert any(c[1:3] == ["-m", "venv"] for c in calls) and li.is_installed(addon)


def test_a_failed_install_is_remembered_for_settings_and_forgotten_once_one_succeeds(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    with pytest.raises(li.LayaInstallError):
        li.install(addon, lambda _: None, opener=serving({}), run=fake_run(), files=PINS)
    assert li.last_failure(addon) and "not found" in (li.last_failure(addon) or "")
    li.install(addon, lambda _: None, opener=serving(DATA), run=fake_run(), files=PINS)
    assert li.last_failure(addon) is None and li.is_installed(addon)


def test_removing_the_add_on_forgets_an_old_failure(tmp_path: Path) -> None:
    addon = tmp_path / "laya"
    with pytest.raises(li.LayaInstallError):
        li.install(addon, lambda _: None, opener=serving({}), run=fake_run(), files=PINS)
    li.remove(addon)
    assert li.last_failure(addon) is None


async def test_settings_shows_why_an_install_made_outside_it_failed(tmp_path: Path) -> None:
    from lilly.app.laya import LayaService
    addon = tmp_path / "addons" / "laya"
    with pytest.raises(li.LayaInstallError):
        li.install(addon, lambda _: None, opener=serving({}), run=fake_run(), files=PINS)      # e.g. by install.sh
    status = LayaService(addon).status()
    assert status["installed"] is False and "not found" in str(status["error"])

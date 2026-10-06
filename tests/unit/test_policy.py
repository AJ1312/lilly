"""The policy kernel: pure rules, no I/O except the path scope's realpath."""
from __future__ import annotations

from pathlib import Path

import pytest

from lilly.domain.labels import ApprovalMode, Label, Mode, Risk, TaskCtx, ToolCall, Verdict
from lilly.domain.policy import PathScope, decide

SCOPE = PathScope(["/tmp"])


def verdict(call: ToolCall, **ctx: object) -> Verdict:
    return decide(call, TaskCtx(**ctx), SCOPE)[0]  # type: ignore[arg-type]


def test_read_only_public_tool_is_allowed() -> None:
    assert verdict(ToolCall("system.stats", Risk.R0)) is Verdict.ALLOW


def test_forbidden_tool_is_denied_in_every_mode() -> None:
    for mode in Mode:
        assert verdict(ToolCall("x", Risk.R3), mode=mode) is Verdict.DENY


def test_changes_need_approval_unless_open() -> None:
    call = ToolCall("fs.write", Risk.R1)
    assert verdict(call, mode=Mode.ASK) is Verdict.NEEDS_APPROVAL
    assert verdict(call, mode=Mode.LOCKED) is Verdict.NEEDS_APPROVAL
    assert verdict(call, mode=Mode.OPEN) is Verdict.ALLOW


def test_approval_modes_are_separate_from_private_data_mode() -> None:
    call = ToolCall("fs.write", Risk.R1)
    assert verdict(call, mode=Mode.ASK, approval_mode=ApprovalMode.MANUAL) is Verdict.NEEDS_APPROVAL
    assert verdict(call, mode=Mode.ASK, approval_mode=ApprovalMode.AUTO) is Verdict.ALLOW
    assert verdict(call, mode=Mode.ASK, approval_mode=ApprovalMode.OFF) is Verdict.DENY


def test_untrusted_content_forces_approval_even_in_open_mode() -> None:
    """Rule of Two: a poisoned page must not be able to change anything unattended."""
    assert verdict(ToolCall("fs.write", Risk.R1), mode=Mode.OPEN, tainted=True) is Verdict.NEEDS_APPROVAL


def test_secrets_never_leave_and_are_never_read_by_agents() -> None:
    assert verdict(ToolCall("web.fetch", Risk.R0, egress=True), mode=Mode.OPEN, label=Label.SECRET) is Verdict.DENY
    assert verdict(ToolCall("x", Risk.R0, reads_label=Label.SECRET), mode=Mode.OPEN) is Verdict.DENY


def test_private_reads_follow_the_mode() -> None:
    read = ToolCall("fs.read", Risk.R0, reads_label=Label.PERSONAL)
    assert verdict(read, mode=Mode.LOCKED) is Verdict.DENY
    assert verdict(read, mode=Mode.ASK) is Verdict.NEEDS_APPROVAL
    assert verdict(read, mode=Mode.OPEN) is Verdict.ALLOW


def test_private_data_cannot_leave_after_untrusted_content_even_when_open() -> None:
    send = ToolCall("web.fetch", Risk.R0, egress=True)
    assert verdict(send, mode=Mode.OPEN, label=Label.PERSONAL, tainted=True) is Verdict.NEEDS_APPROVAL
    assert verdict(send, mode=Mode.LOCKED, label=Label.PERSONAL) is Verdict.DENY


def test_most_restrictive_rule_wins() -> None:
    call = ToolCall("x", Risk.R1, paths=("/etc/passwd",))
    assert verdict(call, mode=Mode.OPEN) is Verdict.DENY  # path outside the roots beats everything


def test_path_scope_blocks_traversal_symlinks_and_denied_folders(tmp_path: Path) -> None:
    root, outside, vault = tmp_path / "shared", tmp_path / "outside", tmp_path / "shared" / "vault"
    for d in (root, outside, vault):
        d.mkdir(parents=True, exist_ok=True)
    (root / "link").symlink_to(outside)
    scope = PathScope([str(root)], deny=[str(vault)])
    assert scope.allows(str(root / "a.txt"))
    assert not scope.allows(str(root / ".." / "outside"))
    assert not scope.allows(str(root / "link" / "secret.txt"))
    assert not scope.allows(str(vault / "token"))
    assert not scope.allows("") and not scope.allows("a\x00b")
    assert not PathScope([]).allows(str(root))


@pytest.mark.parametrize("label", list(Label))
def test_context_label_and_taint_only_go_up(label: Label) -> None:
    ctx = TaskCtx(Label.PERSONAL, True).absorb(label, False)
    assert ctx.label >= Label.PERSONAL and ctx.tainted


def test_a_denied_folder_stays_denied_under_another_spelling(tmp_path: Path) -> None:
    """macOS and Windows file systems ignore case (and accents' form): `.LILLY` is Lilly's own `.lilly` there, so a
    path spelled differently must not slip past the deny list. Folding names makes the check spelling-proof."""
    home, vault = tmp_path / "home", tmp_path / "home" / ".lilly"
    vault.mkdir(parents=True)
    scope = PathScope([str(home)], deny=[str(vault)])
    for spelled in (".lilly", ".LILLY", ".Lilly"):
        assert not scope.allows(str(home / spelled / "config" / "access-token"))
        assert not scope.allows(str(home / spelled))
    assert scope.allows(str(home / ".lillys" / "notes.txt")) and scope.allows(str(home / "notes.txt"))
    assert scope.shields(home) and scope.shields(home.parent / "HOME")      # a folder holding it, however spelled
    assert not scope.shields(home / "other")
    assert scope.denies(home / ".LILLY" / "x") and not scope.denies(home / "x")


def test_accents_in_a_denied_folder_name_match_in_either_unicode_form(tmp_path: Path) -> None:
    import unicodedata

    nfc, nfd = unicodedata.normalize("NFC", "café"), unicodedata.normalize("NFD", "café")
    assert nfc != nfd
    scope = PathScope([str(tmp_path)], deny=[str(tmp_path / nfc)])
    assert not scope.allows(str(tmp_path / nfd / "key"))

"""The pre-check: what this computer can do, found out before anything is downloaded."""
from __future__ import annotations

from pathlib import Path

from lilly.decide import laya_install as li
from lilly.decide.laya_pins import DOWNLOAD_BYTES
from tests.unit.test_laya_install import APPLE, INTEL, fake_run

GB = 1024**3


def check(tmp_path: Path, host: li.Host = APPLE, *, free: int = 50 * GB, versions: dict[str, str] | None = None,
          which: dict[str, str] | None = None, base: str = "/usr/bin/py") -> dict[str, li.Check]:
    found = li.preflight(tmp_path / "addons" / "laya", host=host, base_python=base, run=fake_run(versions=versions),
                         which=lambda name: (which or {}).get(name), free_bytes=lambda path: free)
    return {c.name: c for c in found}


def test_a_computer_that_can_run_laya_passes_every_check_and_says_what_will_be_used(tmp_path: Path) -> None:
    found = check(tmp_path)
    assert list(found) == ["This computer", "Python", "Disk space", "Download"]
    assert all(c.ok for c in found.values())
    assert "/usr/bin/py" in found["Python"].detail and "3.12" in found["Python"].detail
    assert str(DOWNLOAD_BYTES // 10**6) in found["Download"].detail
    assert "huggingface.co" in found["Download"].detail and "pypi.org" in found["Download"].detail


def test_too_little_free_disk_fails_with_both_numbers(tmp_path: Path) -> None:
    disk = check(tmp_path, free=2 * GB)["Disk space"]
    assert not disk.ok and "2.0 GB" in disk.detail and "5.0 GB" in disk.detail
    assert check(tmp_path, free=li.FREE_SPACE_NEEDED)["Disk space"].ok


def test_disk_is_measured_where_the_add_on_will_live_even_before_that_folder_exists(tmp_path: Path) -> None:
    asked: list[Path] = []
    li.preflight(tmp_path / "not" / "yet" / "laya", host=APPLE, run=fake_run(), base_python="/usr/bin/py",
                 which=lambda n: None, free_bytes=lambda p: asked.append(p) or 10 * GB)
    assert asked and asked[0].exists()


def test_no_usable_python_fails_and_says_what_to_install(tmp_path: Path) -> None:
    py = check(tmp_path, versions={"/usr/bin/py": "3 9"})["Python"]
    assert not py.ok and "3.10" in py.detail


def test_an_intel_mac_with_only_a_new_python_is_told_exactly_what_to_install(tmp_path: Path) -> None:
    found = check(tmp_path, INTEL, versions={"/usr/bin/py": "3 13"})
    assert found["This computer"].ok and "Intel" in found["This computer"].detail and "3.12" in found["This computer"].detail
    assert not found["Python"].ok and "brew install python@3.12" in found["Python"].detail


def test_an_intel_mac_with_an_older_python_on_the_path_is_fine_and_names_it(tmp_path: Path) -> None:
    found = check(tmp_path, INTEL, versions={"/usr/bin/py": "3 13"}, which={"python3.12": "/opt/py312"})
    assert found["Python"].ok and "/opt/py312" in found["Python"].detail


def test_a_system_laya_has_no_support_for_is_a_failed_check(tmp_path: Path) -> None:
    found = check(tmp_path, li.Host("freebsd", "amd64"))
    assert not found["This computer"].ok and "freebsd" in found["This computer"].detail

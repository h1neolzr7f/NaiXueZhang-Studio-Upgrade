from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_aliases_delegate_to_existing_entrypoints() -> None:
    setup = (ROOT / "scripts" / "setup_windows.ps1").read_text(encoding="utf-8")
    tests = (ROOT / "scripts" / "run_tests_windows.ps1").read_text(encoding="utf-8")
    build = (ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    doctor = (ROOT / "scripts" / "doctor_windows.ps1").read_text(encoding="utf-8")
    assert "INSTALL.bat" in setup
    assert "GALLERY_NONINTERACTIVE" in setup
    assert "verify.ps1" in tests
    assert "make_release.ps1" in build
    assert "read-only" in doctor.lower()
    assert "pip install" not in doctor.lower()

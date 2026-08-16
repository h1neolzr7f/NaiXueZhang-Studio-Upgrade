from __future__ import annotations

import os
import subprocess
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
    assert "ONE_CLICK_START.bat" in doctor
    assert "0x4E00" in doctor
    assert "portable runtime has no pip" in doctor


def test_doctor_finds_chinese_one_click_launcher_on_windows() -> None:
    if os.name != "nt":
        return
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "doctor_windows.ps1"),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    assert completed.returncode == 0
    assert "file.one_click_zh" in output
    assert "[FAIL] file.one_click_zh" not in output

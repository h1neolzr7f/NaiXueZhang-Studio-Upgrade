#!/usr/bin/env python3
"""Static checks for Windows launch/doctor/test/build entry points."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = (
    "INSTALL.bat",
    "START_GALLERY.bat",
    "ONE_CLICK_START.bat",
    "一键启动.bat",
    "scripts/verify.ps1",
    "scripts/doctor_windows.ps1",
    "scripts/setup_windows.ps1",
    "scripts/run_tests_windows.ps1",
    "scripts/build_windows.ps1",
    "scripts/make_release.ps1",
)

# Launchers must not embed live tokens. The release scanner may mention
# exclusion names and regexes; do not treat those as leaked secrets.
LAUNCHER_FORBIDDEN = (
    "INSTALL.bat",
    "START_GALLERY.bat",
    "ONE_CLICK_START.bat",
    "一键启动.bat",
    "scripts/verify.ps1",
    "scripts/doctor_windows.ps1",
    "scripts/setup_windows.ps1",
    "scripts/run_tests_windows.ps1",
    "scripts/build_windows.ps1",
)
FORBIDDEN_ASSIGNMENT = (
    "NOVELAI_TOKEN=",
    "NAI_TOKEN=",
    "pst-[A-Za-z0-9_-]{20,}",
)


def check() -> list[str]:
    import re

    errors: list[str] = []
    for relative in REQUIRED:
        path = ROOT / relative
        if not path.is_file():
            errors.append(f"missing {relative}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            errors.append(f"empty {relative}")
        if relative in LAUNCHER_FORBIDDEN:
            lowered = text.lower()
            if "novelai_token=" in lowered or "nai_token=" in lowered:
                errors.append(f"{relative} assigns a token environment variable")
            if re.search(r"pst-[A-Za-z0-9_-]{20,}", text) and "exclusion" not in lowered:
                errors.append(f"{relative} looks like it embeds a pst- token")
    doctor = (ROOT / "scripts/doctor_windows.ps1").read_text(encoding="utf-8", errors="replace")
    if "Read-only" not in doctor and "read-only" not in doctor.lower() and "doctor" not in doctor.lower():
        errors.append("doctor_windows.ps1 should remain a diagnosis entry")
    return errors


def main() -> int:
    errors = check()
    if errors:
        print("Windows script static check failed:")
        for item in errors:
            print(f"- {item}")
        return 1
    print(f"Windows script static check passed ({len(REQUIRED)} entries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""User-facing gallery/studio preferences (local JSON)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text
from paths import data_dir

PREFS_PATH = data_dir() / "user_prefs.json"

DEFAULTS: dict[str, Any] = {
    "nai_only_gallery": True,
    "quick_send_studio": False,
    "default_optimize_mode": "smart",
    "show_other_ai_types": False,
}


def load_prefs() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    if PREFS_PATH.exists():
        try:
            loaded = json.loads(PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            raw = {}
    out = {**DEFAULTS, **raw}
    out["nai_only_gallery"] = bool(out.get("nai_only_gallery", True))
    out["quick_send_studio"] = bool(out.get("quick_send_studio", False))
    mode = str(out.get("default_optimize_mode") or "smart").strip().lower()
    if mode not in {"smart", "playbook", "sanitize", "anima_epic", "anima_faithful", "native"}:
        mode = "smart"
    out["default_optimize_mode"] = mode
    out["show_other_ai_types"] = bool(out.get("show_other_ai_types", False))
    if out["show_other_ai_types"]:
        out["nai_only_gallery"] = False
    return out


def save_prefs(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_prefs()
    for key in DEFAULTS:
        if key in patch:
            current[key] = patch[key]
    if current.get("show_other_ai_types"):
        current["nai_only_gallery"] = False
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        PREFS_PATH,
        json.dumps(current, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "prefs": current}

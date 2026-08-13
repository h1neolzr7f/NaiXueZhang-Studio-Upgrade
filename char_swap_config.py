"""角色插件可网页编辑的配置（预设、去尼开关等）。"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from nai_prompt_profiles import normalize_prompt_profile
from paths import data_dir

ROOT = Path(__file__).resolve().parent
CONFIG_PATH: Path | None = None
CONFIG_LOCK = threading.RLock()

DEFAULTS: dict[str, Any] = {
    "sanitize_racial": True,
    "sanitize_gore": True,
    "sanitize_creature": False,
    "replace_creature_slots": True,
    "creature_replace_gender": "male",
    "force_free": False,
    "preserve_action": False,
    "preserve_center": True,
    "auto_sanitize_on_generate": True,
    "plugin_enabled": True,
    "prompt_profile": "native",
    "custom_presets": {"male": [], "female": []},
    "style_presets": [
        {
            "id": "granblue",
            "label": "Granblue 画风",
            "style": "granblue_fantasy_(style)",
        },
        {
            "id": "clear_style",
            "label": "去掉画风",
            "style": "",
        },
    ],
}


def _normalize_char_presets_list(presets: Any) -> list[dict[str, Any]]:
    if not isinstance(presets, list):
        return []
    out: list[dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        entry = {
            "id": str(item.get("id") or f"custom_{len(out)}").strip() or f"custom_{len(out)}",
            "label": str(item.get("label") or "自定义角色").strip() or "自定义角色",
            "gender": str(item.get("gender") or "female"),
            "identity": list(item.get("identity") or []),
            "body": list(item.get("body") or []),
            "appearance": list(item.get("appearance") or []),
            "clothing": str(item.get("clothing") or "").strip(),
            "extra": str(item.get("extra") or "").strip(),
            "remove": list(item.get("remove") or []) if isinstance(item.get("remove"), (list, tuple)) else [x.strip() for x in str(item.get("remove") or "").split(",") if x.strip()],
        }
        kind = str(item.get("kind") or "").strip().lower()
        char_caption = str(item.get("char_caption") or "").strip()
        if kind == "oc" or char_caption:
            entry["kind"] = "oc"
            if char_caption:
                entry["char_caption"] = char_caption
        if bool(item.get("hooded")):
            entry["hooded"] = True
        # clean empty
        for k in ("clothing", "extra"):
            if not entry.get(k):
                entry.pop(k, None)
        if not entry.get("remove"):
            entry.pop("remove", None)
        out.append(entry)
    return out


def _normalize_style_presets_list(presets: Any) -> list[dict[str, Any]]:
    if not isinstance(presets, list):
        return list(DEFAULTS["style_presets"])
    out: list[dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        style = item.get("style")
        if style is None:
            style = item.get("replace", "")
        label = str(item.get("label") or "").strip() or "画风预设"
        preset_id = str(item.get("id") or f"style_{len(out)}").strip() or f"style_{len(out)}"
        out.append({"id": preset_id, "label": label, "style": str(style or "")})
    return out or list(DEFAULTS["style_presets"])


def _config_path() -> Path:
    return Path(CONFIG_PATH) if CONFIG_PATH is not None else data_dir() / "char_swap_config.json"


def load_config() -> dict[str, Any]:
    with CONFIG_LOCK:
        path = _config_path()
        if not path.exists():
            return dict(DEFAULTS)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return dict(DEFAULTS)
        merged = dict(DEFAULTS)
        merged.update(data)
        if not isinstance(merged.get("custom_presets"), dict):
            merged["custom_presets"] = {"male": [], "female": []}
        else:
            custom = merged["custom_presets"]
            merged["custom_presets"] = {
                "male": _normalize_char_presets_list(custom.get("male")),
                "female": _normalize_char_presets_list(custom.get("female")),
            }
        merged["style_presets"] = _normalize_style_presets_list(merged.get("style_presets"))
        merged["prompt_profile"] = normalize_prompt_profile(merged.get("prompt_profile"))
        return merged


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    with CONFIG_LOCK:
        cfg = load_config()
        allowed = set(DEFAULTS.keys())
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "custom_presets" and isinstance(value, dict):
                cfg["custom_presets"] = {
                    "male": _normalize_char_presets_list(value.get("male")),
                    "female": _normalize_char_presets_list(value.get("female")),
                }
            elif key == "style_presets" and isinstance(value, list):
                cfg["style_presets"] = _normalize_style_presets_list(value)
            elif key == "prompt_profile":
                cfg["prompt_profile"] = normalize_prompt_profile(value)
            else:
                cfg[key] = value
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return cfg

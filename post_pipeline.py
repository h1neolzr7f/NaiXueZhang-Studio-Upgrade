"""试生成图后处理：超分 → 打码(可选 ANR) → 清元数据。参考 ANR ai_pipeline，保持精简。"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from paths import DeferredDataPath, data_dir

DATA_DIR = DeferredDataPath(lambda: data_dir())
GENERATED_DIR = DeferredDataPath(lambda: data_dir() / "generated")
CONFIG_PATH = DeferredDataPath(lambda: data_dir() / "post_pipeline.json")

DEFAULTS: dict[str, Any] = {
    "anr_root": "",
    "upscale": {"enabled": True, "scale": 2},
    "mosaic": {
        "enabled": False,
        "method": "像素",
        "intensity": 24,
        "parts": ["欧金金", "欧芒果", "欧派派"],
    },
    "metadata": {
        "enabled": True,
        "custom_note": "",
        "custom_note_key": "pixiv-nai-gallery",
        "png_text": {},
    },
    "auto_after_generate": True,
    "keep_original": True,
}


def _candidate_anr_roots() -> list[Path]:
    roots: list[Path] = []
    for raw in (
        os.environ.get("ANR_ROOT", ""),
        "E:/ai批量生图/Auto-NovelAI-Refactor",
        "E:/ai\u6279\u91cf\u751f\u56fe/Auto-NovelAI-Refactor",
        str(Path.home() / "Desktop" / "Auto-NovelAI-Refactor"),
    ):
        if raw:
            roots.append(Path(raw).expanduser())
    return roots


def discover_anr_root() -> str:
    for root in _candidate_anr_roots():
        if _resolve_anr_cwd({"anr_root": str(root)}):
            return str(root.resolve())
    return ""

_LOCK = threading.Lock()
_ANR_RUNTIME_CACHE: dict[str, Any] = {"sig": None, "result": None, "cached_at": 0.0}
_ANR_RUNTIME_TTL_SEC = 30.0
_STEM_LOCKS: dict[str, threading.Lock] = {}
_STEM_LOCKS_GUARD = threading.Lock()
_ACTIVE_PIPELINE_COUNTS: dict[str, int] = {}
_JOB: dict[str, Any] = {
    "status": "idle",
    "message": "空闲",
    "total": 0,
    "done": 0,
    "ok": 0,
    "fail": 0,
    "items": [],
}
_BACKLOG_CACHE: dict[str, Any] = {
    "sig": None,
    "result": None,
    "cached_at": 0.0,
    "dirty": True,
    "generation": 0,
}
_BACKLOG_REFRESH_LOCK = threading.Lock()
_BACKLOG_TTL_SEC = 45.0


def _stem_lock(stem: str) -> threading.Lock:
    with _STEM_LOCKS_GUARD:
        lock = _STEM_LOCKS.get(stem)
        if lock is None:
            lock = threading.Lock()
            _STEM_LOCKS[stem] = lock
        return lock


def pipeline_status() -> dict[str, Any]:
    with _LOCK:
        return {**dict(_JOB), "active_image_ids": sorted(_ACTIVE_PIPELINE_COUNTS)}


def cancel_pipeline() -> dict[str, Any]:
    """Request a running post-process job to stop after the current image."""
    with _LOCK:
        if _JOB.get("status") not in {"running", "cancelling"}:
            return {"ok": False, "message": "没有运行中的流水线", "job": dict(_JOB)}
        _JOB["cancel_requested"] = True
        _JOB["status"] = "cancelling"
        _JOB["message"] = "正在取消…"
        return {"ok": True, "job": dict(_JOB)}


def active_pipeline_ids() -> set[str]:
    with _LOCK:
        return set(_ACTIVE_PIPELINE_COUNTS)


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass
    if not isinstance(cfg.get("upscale"), dict):
        cfg["upscale"] = dict(DEFAULTS["upscale"])
    if not isinstance(cfg.get("mosaic"), dict):
        cfg["mosaic"] = dict(DEFAULTS["mosaic"])
    if not isinstance(cfg.get("metadata"), dict):
        cfg["metadata"] = dict(DEFAULTS["metadata"])
    if not str(cfg.get("anr_root") or "").strip():
        found = discover_anr_root()
        if found:
            cfg["anr_root"] = found
    return cfg


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    for key in ("anr_root", "auto_after_generate", "keep_original"):
        if key in updates:
            cfg[key] = updates[key]
    for block in ("upscale", "mosaic", "metadata"):
        if block in updates and isinstance(updates[block], dict):
            cfg[block] = {**cfg.get(block, {}), **updates[block]}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    invalidate_backlog_cache()
    return cfg


def _meta_path(png: Path) -> Path:
    return png.with_suffix(png.suffix + ".meta.json")


def _read_meta(png: Path) -> dict[str, Any]:
    path = _meta_path(png)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_meta(png: Path, meta: dict[str, Any]) -> None:
    _meta_path(png).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def manual_review_image(image_id: str, action: str, note: str = "") -> dict[str, Any]:
    """Persist a human review decision for a generated image."""
    import shutil

    from generated_gallery import invalidate_scan_cache

    stem = _stem_from_image_id(image_id)
    source = GENERATED_DIR / f"{stem}.png"
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"generated image not found: {stem}")

    act = str(action or "").strip().lower()
    now = datetime.now().isoformat(timespec="seconds")
    meta = _read_meta(source)
    review = {
        "status": "",
        "at": now,
        "note": str(note or "").strip(),
    }

    if act in {"approve", "approved", "pass"}:
        final_path = GENERATED_DIR / _final_name(stem)
        tmp_final_path = final_path.with_name(f"{final_path.stem}.tmp{final_path.suffix}")
        try:
            from PIL import Image, ImageOps, ImageFile

            ImageFile.LOAD_TRUNCATED_IMAGES = True
            with Image.open(source) as img:
                img = ImageOps.exif_transpose(img)
                mode = "RGBA" if img.mode in {"RGBA", "LA"} else "RGB"
                clean = Image.new(mode, img.size)
                clean.paste(img.convert(mode))
                clean.save(tmp_final_path)
        except Exception:
            clean_path = _strip_metadata(source, {"pipeline_marker": False})
            shutil.copy2(clean_path, tmp_final_path)
        tmp_final_path.replace(final_path)
        review["status"] = "approved"
        steps = [s for s in (meta.get("pipeline_steps") or []) if not str(s).startswith("manual_review:")]
        steps.append("manual_review:approved")
        meta.update(
            {
                "manual_review": review,
                "pipeline_at": now,
                "pipeline_steps": steps,
                "processed_filename": final_path.name,
                "processed_url": f"/data/generated/{final_path.name}",
            }
        )
        _write_meta(source, meta)
        _write_meta(
            final_path,
            {
                **meta,
                "id": f"{stem}_final",
                "filename": final_path.name,
                "image_url": f"/data/generated/{final_path.name}",
                "source_image": source.name,
                "is_pipeline_output": True,
            },
        )
        invalidate_scan_cache()
        invalidate_backlog_cache()
        return {
            "ok": True,
            "id": stem,
            "action": "approved",
            "final_filename": final_path.name,
            "final_url": f"/data/generated/{final_path.name}",
            "message": "已人工通过，并生成上传用 final 文件",
        }

    if act in {"exclude", "excluded", "reject", "remove"}:
        review["status"] = "excluded"
        steps = [s for s in (meta.get("pipeline_steps") or []) if not str(s).startswith("manual_review:")]
        steps.append("manual_review:excluded")
        meta.update(
            {
                "manual_review": review,
                "pipeline_at": now,
                "pipeline_steps": steps,
            }
        )
        _write_meta(source, meta)
        invalidate_scan_cache()
        invalidate_backlog_cache()
        return {
            "ok": True,
            "id": stem,
            "action": "excluded",
            "message": "已人工剔除，后续批量上传会跳过此图",
        }

    raise ValueError("action must be approve or exclude")


def mosaic_runtime_status(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """检测 ANR 打码插件是否可用，不在页面状态接口里加载检测模型。"""
    cfg = cfg or load_config()
    anr_cwd = _resolve_anr_cwd(cfg)
    if not anr_cwd:
        return {
            "ok": False,
            "anr_root": str(cfg.get("anr_root") or ""),
            "message": "未找到 ANR 打码插件，请检查 post_pipeline.json 的 anr_root",
        }
    sig = str(anr_cwd)
    now = time.monotonic()
    cached = _ANR_RUNTIME_CACHE
    if cached.get("sig") == sig and now - float(cached.get("cached_at") or 0.0) < _ANR_RUNTIME_TTL_SEC:
        return dict(cached.get("result") or {})

    plugin_dir = anr_cwd / "plugins" / "anr_plugin_auto_mosaics"
    required = [
        plugin_dir / "detector.py",
        plugin_dir / "mosaics.py",
        plugin_dir / "__init__.py",
    ]
    missing = [p.name for p in required if not p.exists()]
    if missing:
        result = {
            "ok": False,
            "anr_root": str(anr_cwd),
            "message": "ANR 打码插件缺少文件：" + ", ".join(missing),
        }
    else:
        result = {
            "ok": True,
            "anr_root": str(anr_cwd),
            "message": "ANR 打码插件已找到",
        }
    _ANR_RUNTIME_CACHE.update({"sig": sig, "result": dict(result), "cached_at": now})
    return result


def _resolve_anr_cwd(cfg: dict[str, Any]) -> Path | None:
    root = Path(str(cfg.get("anr_root") or "")).expanduser()
    candidates = [
        root,
        root / "release" / "ANR_Full_Auto_Suite_20260528" / "payload" / "core",
        root / "release" / "理塘魔改版肘击王_小白一键包_20260606-2145" / "软件本体-安装文件勿删",
    ]
    for base in candidates:
        if not base.exists():
            continue
        if (base / "plugins" / "anr_plugin_auto_mosaics").exists():
            return base.resolve()
    return None


def _upscale_lanczos(source: Path, scale: int) -> Path:
    from PIL import Image, ImageOps

    scale = max(1, min(int(scale or 2), 4))
    out = source.with_name(f"{source.stem}_up{scale}x{source.suffix}")
    if out.exists():
        return out
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        if scale > 1:
            resampling = getattr(Image, "Resampling", None)
            method = resampling.LANCZOS if resampling else Image.LANCZOS
            img = img.resize((img.width * scale, img.height * scale), method)
        mode = "RGBA" if img.mode in {"RGBA", "LA"} else "RGB"
        img.convert(mode).save(out)
    return out


def _metadata_step_name(meta_cfg: dict[str, Any] | None) -> str:
    meta_cfg = meta_cfg if isinstance(meta_cfg, dict) else {}
    note = str(meta_cfg.get("custom_note") or "").strip()
    png_text = meta_cfg.get("png_text") or {}
    if note or (isinstance(png_text, dict) and png_text):
        return "metadata:replace"
    return "metadata:clean"


def _safe_png_text_key(key: str, fallback: str = "pixiv-nai-gallery") -> str:
    raw = str(key or "").strip() or fallback
    safe = re.sub(r"[^A-Za-z0-9 _.-]+", "-", raw).strip(" .-")
    if not safe and raw:
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        safe = f"{fallback}-{digest}"
    return safe[:79] or fallback


def _png_add_text(meta: Any, key: str, value: Any) -> None:
    safe_key = _safe_png_text_key(key)
    text = str(value if value is not None else "")
    try:
        text.encode("latin-1", "strict")
        meta.add_text(safe_key, text)
    except UnicodeEncodeError:
        meta.add_itxt(safe_key, text)


def _strip_metadata(source: Path, meta_cfg: dict[str, Any] | str | None = None) -> Path:
    from PIL import Image, ImageOps
    from PIL.PngImagePlugin import PngInfo

    if isinstance(meta_cfg, str):
        meta_cfg = {"custom_note": meta_cfg}
    meta_cfg = meta_cfg if isinstance(meta_cfg, dict) else {}

    out = source.with_name(f"{source.stem}_clean{source.suffix}")
    with Image.open(source) as img:
        img = ImageOps.exif_transpose(img)
        mode = "RGBA" if img.mode in {"RGBA", "LA"} else "RGB"
        clean = Image.new(mode, img.size)
        clean.paste(img.convert(mode))
        meta = PngInfo()
        png_text = meta_cfg.get("png_text") or {}
        if isinstance(png_text, dict):
            for key, value in png_text.items():
                k = str(key or "").strip()
                if not k:
                    continue
                _png_add_text(meta, k, value)
        note = str(meta_cfg.get("custom_note") or "").strip()
        if note:
            note_key = str(meta_cfg.get("custom_note_key") or "pixiv-nai-gallery").strip()
            _png_add_text(meta, note_key or "pixiv-nai-gallery", note)
        if meta_cfg.get("pipeline_marker", True) is not False:
            _png_add_text(
                meta,
                "aitag-pipeline",
                f"cleaned_at={datetime.now().isoformat(timespec='seconds')}",
            )
        clean.save(out, pnginfo=meta)
    return out


def _stem_from_image_id(image_id: str) -> str:
    return Path(str(image_id or "")).stem


def _base_stem(stem: str) -> str:
    """去掉超分/打码/清元数据后缀，回到试生成图主 stem。"""
    current = str(stem or "")
    while True:
        stripped = re.sub(
            r"(_up\d+x(?:_(?:mosaic|clean))?|_mosaic|_clean)$",
            "",
            current,
        )
        if stripped == current:
            return current
        current = stripped


def _artifact_rank(path: Path) -> tuple[int, int, str]:
    """越大越接近流水线末端（clean > mosaic > upscale）。"""
    name = path.stem
    if name.endswith("_clean") or re.search(r"_up\d+x_clean$", name):
        return (3, len(name), name)
    if "_mosaic" in name:
        return (2, len(name), name)
    if re.search(r"_up\d+x$", name):
        return (1, len(name), name)
    return (0, len(name), name)


def _pipeline_artifacts(stem: str) -> list[Path]:
    artifacts: list[Path] = []
    for path in GENERATED_DIR.glob(f"{stem}*.png"):
        if path.stem in {stem, f"{stem}_final"}:
            continue
        artifacts.append(path)
    artifacts.sort(key=_artifact_rank, reverse=True)
    return artifacts


def _expected_pipeline_output(
    stem: str,
    cfg: dict[str, Any],
    artifact_index: dict[str, dict[str, list[Path]]] | None = None,
) -> Path | None:
    """流水线末端产物：final 应与此文件内容一致。"""
    meta_cfg = cfg.get("metadata") or {}
    mosaic_cfg = cfg.get("mosaic") or {}
    upscale_cfg = cfg.get("upscale") or {}
    if meta_cfg.get("enabled", True):
        clean = _find_artifact(
            stem,
            "clean",
            artifact_index=artifact_index,
        )
        if clean and clean.exists():
            return clean
    if mosaic_cfg.get("enabled"):
        mosaic = _find_artifact(
            stem,
            "mosaic",
            artifact_index=artifact_index,
        )
        if mosaic and mosaic.exists():
            return mosaic
    if upscale_cfg.get("enabled", True):
        up = _find_artifact(
            stem,
            "upscale",
            artifact_index=artifact_index,
        )
        if up and up.exists():
            return up
    source = GENERATED_DIR / f"{stem}.png"
    return source if source.exists() else None


def _final_is_stale(
    stem: str,
    *,
    overrides: dict[str, Any] | None = None,
    artifact_index: dict[str, dict[str, list[Path]]] | None = None,
    resolved_config: dict[str, Any] | None = None,
) -> bool:
    final_path = GENERATED_DIR / f"{stem}_final.png"
    cfg = (
        resolved_config
        if isinstance(resolved_config, dict)
        else merge_pipeline_config(overrides)
    )
    source = GENERATED_DIR / f"{stem}.png"
    if not final_path.exists():
        expected = _expected_pipeline_output(
            stem,
            cfg,
            artifact_index=artifact_index,
        )
        if expected and source.exists() and expected.resolve() != source.resolve():
            return True
        meta = _read_meta(source) if source.exists() else {}
        if meta.get("pipeline_steps") or meta.get("processed_filename"):
            return True
        return False
    expected = _expected_pipeline_output(
        stem,
        cfg,
        artifact_index=artifact_index,
    )
    if expected and expected.resolve() != final_path.resolve():
        try:
            if expected.stat().st_mtime > final_path.stat().st_mtime + 0.5:
                return True
        except OSError:
            return True
    meta = _read_meta(source) if source.exists() else {}
    pipeline_at = str(meta.get("pipeline_at") or "").strip()
    if pipeline_at:
        try:
            from datetime import datetime

            if (
                datetime.fromisoformat(pipeline_at).timestamp()
                > final_path.stat().st_mtime + 0.5
            ):
                return True
        except (OSError, ValueError):
            return True
    return False


def _path_mtime(path: Path | None) -> float | None:
    if not path:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _last_step_index(steps: list[str], prefixes: tuple[str, ...]) -> int:
    found = -1
    for idx, step in enumerate(steps):
        if any(step.startswith(prefix) for prefix in prefixes):
            found = idx
    return found


def _build_artifact_index() -> dict[str, dict[str, list[Path]]]:
    """Index every derived PNG in one directory pass for backlog checks."""

    index: dict[str, dict[str, list[Path]]] = {}
    try:
        paths = GENERATED_DIR.iterdir()
    except OSError:
        return index
    try:
        for path in paths:
            if not path.is_file() or path.suffix.lower() != ".png":
                continue
            derived_stem = path.stem
            base = _base_stem(derived_stem)
            if base == derived_stem:
                continue
            kind = ""
            if derived_stem.endswith("_clean"):
                kind = "clean"
            elif "_mosaic" in derived_stem:
                kind = "mosaic"
            elif re.search(r"_up\d+x$", derived_stem):
                kind = "upscale"
            if not kind:
                continue
            index.setdefault(base, {}).setdefault(kind, []).append(path)
    except OSError:
        return index
    for kinds in index.values():
        for matches in kinds.values():
            matches.sort()
    return index


def build_artifact_index() -> dict[str, dict[str, list[Path]]]:
    """Public read-only artifact index for callers that inspect many items."""
    return _build_artifact_index()


def _find_artifact(
    stem: str,
    kind: str,
    *,
    artifact_index: dict[str, dict[str, list[Path]]] | None = None,
) -> Path | None:
    if artifact_index is not None:
        matches = artifact_index.get(stem, {}).get(kind, [])
        return matches[-1] if matches else None
    if kind == "mosaic":
        matches = sorted(
            list(GENERATED_DIR.glob(f"{stem}_mosaic.png"))
            + list(GENERATED_DIR.glob(f"{stem}_up*_mosaic.png"))
        )
        return matches[-1] if matches else None
    if kind == "clean":
        matches = sorted(
            list(GENERATED_DIR.glob(f"{stem}_clean.png"))
            + list(GENERATED_DIR.glob(f"{stem}_up*_clean.png"))
        )
        return matches[-1] if matches else None
    if kind == "upscale":
        matches = [
            p
            for p in sorted(GENERATED_DIR.glob(f"{stem}_up*x.png"))
            if "_mosaic" not in p.stem and not p.stem.endswith("_clean")
        ]
        return matches[-1] if matches else None
    return None


def _upscale_output_path(source_stem: str, scale: int) -> Path:
    base = _base_stem(source_stem)
    return GENERATED_DIR / f"{base}_up{max(1, int(scale or 2))}x.png"


def pipeline_item_state(
    image_id: str,
    *,
    overrides: dict[str, Any] | None = None,
    _artifact_index: dict[str, dict[str, list[Path]]] | None = None,
    _config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """检查单张图各后处理步骤是否已完成。"""
    stem = _stem_from_image_id(image_id)
    source = GENERATED_DIR / f"{stem}.png"
    meta = _read_meta(source) if source.exists() else {}
    manual_review = meta.get("manual_review") if isinstance(meta.get("manual_review"), dict) else {}
    manual_status = str(manual_review.get("status") or "").strip().lower()
    steps = [str(s) for s in (meta.get("pipeline_steps") or [])]
    cfg = (
        _config
        if isinstance(_config, dict)
        else merge_pipeline_config(overrides)
    )
    upscale_cfg = cfg.get("upscale") or {}
    mosaic_cfg = cfg.get("mosaic") or {}
    meta_cfg = cfg.get("metadata") or {}
    upscale_enabled = bool(upscale_cfg.get("enabled", True))
    mosaic_enabled = bool(mosaic_cfg.get("enabled"))
    metadata_enabled = bool(meta_cfg.get("enabled", True))

    mosaic_skip = ""
    for step in steps:
        if step.startswith("mosaic:skip"):
            mosaic_skip = step
            break

    source_mtime = _path_mtime(source)
    upscale_path = _find_artifact(
        stem,
        "upscale",
        artifact_index=_artifact_index,
    )
    mosaic_path = _find_artifact(
        stem,
        "mosaic",
        artifact_index=_artifact_index,
    )
    clean_path = _find_artifact(
        stem,
        "clean",
        artifact_index=_artifact_index,
    )
    upscale_mtime = _path_mtime(upscale_path)
    mosaic_mtime = _path_mtime(mosaic_path)
    clean_mtime = _path_mtime(clean_path)
    upstream_mtime = source_mtime

    has_upscale = any(s.startswith("upscale:") for s in steps) or (
        upscale_path is not None
    )
    if upscale_enabled and has_upscale and upscale_mtime is not None:
        upstream_mtime = max(upstream_mtime or 0.0, upscale_mtime)

    has_mosaic_step = any(
        s.startswith("mosaic:") and "skip" not in s for s in steps
    )
    has_mosaic_none = any(s.startswith("mosaic:none") for s in steps)
    has_mosaic_artifact = mosaic_path is not None
    if mosaic_skip:
        has_mosaic = has_mosaic_step
    else:
        has_mosaic = has_mosaic_step or has_mosaic_artifact
    if (
        mosaic_enabled
        and has_mosaic
        and mosaic_mtime is not None
        and upstream_mtime is not None
        and mosaic_mtime + 0.5 < upstream_mtime
    ):
        has_mosaic = False
    if mosaic_enabled and has_mosaic and mosaic_mtime is not None:
        upstream_mtime = max(upstream_mtime or 0.0, mosaic_mtime)

    metadata_index = _last_step_index(steps, ("metadata:clean", "metadata:replace"))
    upstream_step_indexes: list[int] = []
    if upscale_enabled:
        upstream_step_indexes.append(_last_step_index(steps, ("upscale:",)))
    if mosaic_enabled:
        upstream_step_indexes.append(_last_step_index(steps, ("mosaic:",)))
    required_step_index = max([idx for idx in upstream_step_indexes if idx >= 0], default=-1)
    metadata_step_valid = metadata_index >= 0 and metadata_index >= required_step_index
    metadata_artifact_valid = clean_path is not None
    if (
        metadata_artifact_valid
        and clean_mtime is not None
        and upstream_mtime is not None
        and clean_mtime + 0.5 < upstream_mtime
    ):
        metadata_artifact_valid = False
    has_metadata = metadata_step_valid or metadata_artifact_valid
    final_path = GENERATED_DIR / f"{stem}_final.png"

    missing: list[str] = []
    if upscale_enabled and not has_upscale:
        missing.append("upscale")
    if mosaic_enabled and not has_mosaic:
        missing.append("mosaic")
        if mosaic_skip:
            missing.append("mosaic_failed")
    if metadata_enabled and not has_metadata:
        missing.append("metadata")

    final_stale = _final_is_stale(
        stem,
        overrides=overrides,
        artifact_index=_artifact_index,
        resolved_config=cfg,
    )
    if final_stale and final_path.exists():
        missing.append("final_stale")

    if manual_status == "approved" and final_path.exists():
        missing = []
        final_stale = False

    return {
        "id": stem,
        "source_exists": source.exists(),
        "upscale": has_upscale or manual_status == "approved",
        "mosaic": has_mosaic or manual_status == "approved",
        "metadata": has_metadata or manual_status == "approved",
        "final": final_path.exists(),
        "final_stale": final_stale,
        "steps": steps,
        "manual_review": manual_review,
        "manual_status": manual_status,
        "excluded": manual_status == "excluded",
        "mosaic_skip": mosaic_skip,
        "mosaic_no_target": str(meta.get("mosaic_no_target") or "") if has_mosaic_none else "",
        "missing": missing,
        "pipeline_at": meta.get("pipeline_at") or "",
        "processed_url": meta.get("processed_url") or (
            f"/data/generated/{final_path.name}" if final_path.exists() else ""
        ),
    }


def merge_pipeline_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_config()
    if not overrides:
        return cfg
    merged = dict(cfg)
    for key in ("anr_root", "auto_after_generate", "keep_original", "only_missing"):
        if key in overrides:
            merged[key] = overrides[key]
    for block in ("upscale", "mosaic", "metadata"):
        if block in overrides and isinstance(overrides[block], dict):
            merged[block] = {**cfg.get(block, {}), **overrides[block]}
    return merged


def _detector_parts_with_fallback(parts: list[str]) -> list[list[str]]:
    normalized = [str(p).strip() for p in parts if str(p).strip()]
    broad = ["欧金金", "欧芒果", "欧派派"]
    attempts: list[list[str]] = []
    if normalized:
        attempts.append(normalized)
    if set(normalized) != set(broad):
        attempts.append(broad)
    return attempts or [broad]


class MosaicNoTarget(RuntimeError):
    """Raised when ANR runs but finds no selected/broad censor target."""


def _latest_intermediate(stem: str) -> Path | None:
    artifacts = _pipeline_artifacts(stem)
    if artifacts:
        return artifacts[0]
    source = GENERATED_DIR / f"{stem}.png"
    return source if source.exists() else None


def _mosaic_via_anr(source: Path, cfg: dict[str, Any], session_dir: Path) -> Path:
    anr_cwd = _resolve_anr_cwd(cfg)
    if not anr_cwd:
        raise RuntimeError("未找到 ANR 打码插件，请检查 post_pipeline.json 的 anr_root")

    mosaic_cfg = cfg.get("mosaic") or {}
    method = str(mosaic_cfg.get("method") or "像素")
    intensity = int(mosaic_cfg.get("intensity") or 24)
    parts = list(mosaic_cfg.get("parts") or ["欧金金", "欧芒果", "欧派派"])

    session_dir.mkdir(parents=True, exist_ok=True)
    script_path = session_dir / "_run_anr_mosaic.py"
    
    script_content = """# -*- coding: utf-8 -*-
import sys
import os
import json
from pathlib import Path

# Setup paths
anr_cwd = sys.argv[1]
sys.path.insert(0, anr_cwd)
os.chdir(anr_cwd)

source_path = sys.argv[2]
method = sys.argv[3]
intensity = int(sys.argv[4])
attempts = json.loads(sys.argv[5])
session_dir = sys.argv[6]

try:
    from plugins.anr_plugin_auto_mosaics.detector import detector
    from plugins.anr_plugin_auto_mosaics.mosaics import ImageMosaicProcessor
except Exception as exc:
    print(f"ERROR: Failed to import ANR modules: {exc}", file=sys.stderr)
    sys.exit(1)

mask_path = ""
last_detector_error = ""

for attempt_parts in attempts:
    try:
        candidate = detector(source_path, attempt_parts)
        if candidate and Path(candidate).exists():
            mask_path = str(candidate)
            break
        last_detector_error = "ANR 未产出遮罩文件"
    except Exception as exc:
        last_detector_error = str(exc)
        if "need at least one array to stack" not in last_detector_error:
            raise

if not mask_path:
    print(f"ERROR: {last_detector_error or 'ANR 未检测到可打码目标'}", file=sys.stderr)
    sys.exit(10)

try:
    processor = ImageMosaicProcessor()
    if method == "模糊":
        out = processor.blur_mosaic(source_path, mask_path, blur_radius=intensity, output_dir=session_dir)
    elif method == "线条":
        out = processor.line_mosaic(source_path, mask_path, line_width_range=(3, 10), spacing_range=(10, 15), output_dir=session_dir)
    elif method == "纯色":
        out = processor.solid_color_mosaic(source_path, mask_path, color=(128, 128, 128), output_dir=session_dir)
    else:
        out = processor.pixel_mosaic(source_path, mask_path, pixel_size=intensity, output_dir=session_dir)

    if not out or not Path(out).exists():
        print("ERROR: ANR 打码未产出文件", file=sys.stderr)
        sys.exit(2)
        
    print(f"SUCCESS: {out}")
except Exception as exc:
    print(f"ERROR: Image processing failed: {exc}", file=sys.stderr)
    sys.exit(3)
"""
    script_path.write_text(script_content, encoding="utf-8")
    
    attempts = _detector_parts_with_fallback(parts)
    
    import subprocess
    import json
    try:
        res = subprocess.run([
            sys.executable,
            str(script_path.resolve()),
            str(anr_cwd.resolve()),
            str(source.resolve()),
            method,
            str(intensity),
            json.dumps(attempts, ensure_ascii=False),
            str(session_dir.resolve()),
        ], capture_output=True, text=True, encoding="utf-8")
        
        if res.returncode == 10:
            err_msg = res.stderr.strip()
            if err_msg.startswith("ERROR: "):
                err_msg = err_msg[7:]
            raise MosaicNoTarget(err_msg)
        elif res.returncode != 0:
            raise RuntimeError(f"ANR 打码脚本执行失败 (code {res.returncode}):\\n{res.stderr.strip()}")
            
        stdout = res.stdout.strip()
        success_line = [l for l in stdout.splitlines() if l.startswith("SUCCESS: ")]
        if not success_line:
            raise RuntimeError(f"ANR 打码未返回成功结果，输出：\\n{stdout}")
            
        out_path = success_line[0][9:].strip()
        result = Path(out_path).resolve()
        target = GENERATED_DIR / f"{_base_stem(source.stem)}_mosaic{source.suffix}"
        if result != target:
            import shutil

            shutil.copy2(result, target)
            return target
        return result
    finally:
        try:
            if script_path.exists():
                script_path.unlink()
        except Exception:
            pass


def _final_name(stem: str) -> str:
    return f"{stem}_final.png"


def process_image(
    image_id: str,
    *,
    overrides: dict[str, Any] | None = None,
    only_missing: bool = False,
) -> dict[str, Any]:
    """对单张试生成图跑流水线，产出 *_final.png 并回写 meta。"""
    stem = _stem_from_image_id(image_id)
    with _LOCK:
        _ACTIVE_PIPELINE_COUNTS[stem] = _ACTIVE_PIPELINE_COUNTS.get(stem, 0) + 1
    try:
        with _stem_lock(stem):
            return _process_image_locked(
                stem,
                overrides=overrides,
                only_missing=only_missing,
            )
    finally:
        with _LOCK:
            remaining = _ACTIVE_PIPELINE_COUNTS.get(stem, 1) - 1
            if remaining > 0:
                _ACTIVE_PIPELINE_COUNTS[stem] = remaining
            else:
                _ACTIVE_PIPELINE_COUNTS.pop(stem, None)


def _process_image_locked(
    stem: str,
    *,
    overrides: dict[str, Any] | None = None,
    only_missing: bool = False,
) -> dict[str, Any]:
    from generated_gallery import invalidate_scan_cache

    source = GENERATED_DIR / f"{stem}.png"
    if not source.exists():
        raise FileNotFoundError(f"图片不存在: {stem}")

    orig_meta = _read_meta(source)
    if not orig_meta.get("prompt_snapshot"):
        try:
            from nai_char import prompt_snapshot_from_png

            snap = prompt_snapshot_from_png(source)
            if snap:
                orig_meta["prompt_snapshot"] = snap
                _write_meta(source, orig_meta)
        except Exception:
            pass

    cfg = merge_pipeline_config(overrides)
    state = pipeline_item_state(stem, overrides=overrides)
    prev_steps = list(state.get("steps") or [])

    upscale_cfg = cfg.get("upscale") or {}
    mosaic_cfg = cfg.get("mosaic") or {}
    meta_cfg = cfg.get("metadata") or {}

    scale = int(upscale_cfg.get("scale") or 2)
    expected_up = _upscale_output_path(stem, scale)
    has_correct_upscale = expected_up.exists() or any(
        s == f"upscale:{scale}x" for s in prev_steps
    )
    need_upscale = bool(upscale_cfg.get("enabled", True)) and (
        not only_missing or not has_correct_upscale
    )
    need_mosaic = bool(mosaic_cfg.get("enabled")) and (
        not only_missing or not state.get("mosaic")
    )
    need_metadata = bool(meta_cfg.get("enabled", True)) and (
        not only_missing or not state.get("metadata")
    )
    if only_missing:
        # Later steps consume earlier outputs. If we regenerate an upstream
        # artifact, every enabled downstream artifact must be rebuilt too.
        if need_upscale:
            need_mosaic = bool(mosaic_cfg.get("enabled"))
            need_metadata = bool(meta_cfg.get("enabled", True))
        elif need_mosaic:
            need_metadata = bool(meta_cfg.get("enabled", True))

    final_stale = _final_is_stale(stem, overrides=overrides)
    if only_missing and not (need_upscale or need_mosaic or need_metadata) and not final_stale:
        final_path = GENERATED_DIR / _final_name(stem)
        result = {
            "ok": True,
            "id": stem,
            "skipped": True,
            "source": source.name,
            "final_filename": final_path.name if final_path.exists() else "",
            "final_url": f"/data/generated/{final_path.name}" if final_path.exists() else "",
            "steps": prev_steps,
            "message": "后处理步骤已齐全，跳过",
        }
        invalidate_scan_cache()
        return result

    steps: list[str] = []
    if only_missing:
        steps.extend(prev_steps)
    work_dir = GENERATED_DIR / ".pipeline" / stem
    work_dir.mkdir(parents=True, exist_ok=True)

    current = source
    if only_missing:
        latest = _latest_intermediate(stem)
        if latest and latest.exists():
            current = latest

    if need_upscale:
        scale = int(upscale_cfg.get("scale") or 2)
        current = _upscale_lanczos(current, scale)
        steps = [s for s in steps if not s.startswith("upscale:")]
        steps.append(f"upscale:{scale}x")
    elif only_missing and state.get("upscale") and not need_upscale:
        up = _find_artifact(stem, "upscale")
        if up and up.exists():
            current = up

    if need_mosaic:
        runtime = mosaic_runtime_status(cfg)
        if not runtime.get("ok"):
            raise RuntimeError(str(runtime.get("message") or "打码环境未就绪"))
        try:
            current = _mosaic_via_anr(current, cfg, work_dir)
            steps = [s for s in steps if not s.startswith("mosaic:")]
            steps.append(f"mosaic:{mosaic_cfg.get('method', '像素')}")
        except MosaicNoTarget as exc:
            steps = [s for s in steps if not s.startswith("mosaic:")]
            steps.append("mosaic:none")
            orig_meta["mosaic_no_target"] = str(exc)
        except Exception as exc:
            reason = str(exc).strip() or "打码失败"
            steps = [s for s in steps if not s.startswith("mosaic:")]
            steps.append(f"mosaic:skip({reason})")
            raise RuntimeError(f"打码失败: {reason}") from exc
    elif only_missing and state.get("mosaic") and not need_mosaic:
        mosaic_path = _find_artifact(stem, "mosaic")
        if mosaic_path and mosaic_path.exists():
            current = mosaic_path

    if need_metadata:
        current = _strip_metadata(current, meta_cfg)
        meta_step = _metadata_step_name(meta_cfg)
        steps = [s for s in steps if s not in ("metadata:clean", "metadata:replace")]
        steps.append(meta_step)
    elif (
        only_missing
        and state.get("metadata")
        and not need_upscale
        and not need_mosaic
        and not need_metadata
    ):
        clean_path = _find_artifact(stem, "clean")
        if clean_path and clean_path.exists():
            current = clean_path

    final_path = GENERATED_DIR / _final_name(stem)
    if current.resolve() != final_path.resolve():
        import shutil

        shutil.copy2(current, final_path)

    orig_meta = _read_meta(source)
    orig_meta.update(
        {
            "pipeline_at": datetime.now().isoformat(timespec="seconds"),
            "pipeline_steps": steps,
            "processed_filename": final_path.name,
            "processed_url": f"/data/generated/{final_path.name}",
        }
    )
    _write_meta(source, orig_meta)
    _write_meta(
        final_path,
        {
            **orig_meta,
            "id": f"{stem}_final",
            "filename": final_path.name,
            "image_url": f"/data/generated/{final_path.name}",
            "source_image": source.name,
            "is_pipeline_output": True,
        },
    )

    ran = [name for name, flag in (
        ("upscale", need_upscale),
        ("mosaic", need_mosaic),
        ("metadata", need_metadata),
    ) if flag]

    result = {
        "ok": True,
        "id": stem,
        "source": source.name,
        "final_filename": final_path.name,
        "final_url": f"/data/generated/{final_path.name}",
        "steps": steps,
        "ran_steps": ran,
        "message": "流水线完成" if ran else "流水线完成（无新增步骤）",
    }
    invalidate_scan_cache()
    return result


def invalidate_backlog_cache() -> None:
    _BACKLOG_CACHE["sig"] = None
    _BACKLOG_CACHE["dirty"] = True


def _backlog_cache_signature(overrides: dict[str, Any] | None = None) -> tuple[Any, ...]:
    from generated_gallery import _scan_signature

    cfg = merge_pipeline_config(overrides)
    cfg_sig = (
        bool((cfg.get("upscale") or {}).get("enabled", True)),
        bool((cfg.get("mosaic") or {}).get("enabled")),
        bool((cfg.get("metadata") or {}).get("enabled", True)),
        bool(cfg.get("only_missing")),
        str(cfg.get("anr_root") or ""),
    )
    return (_scan_signature(), cfg_sig)


def list_items_needing_pipeline(
    *,
    overrides: dict[str, Any] | None = None,
) -> list[str]:
    """返回仍缺后处理步骤的主图 id 列表（按时间倒序）。"""
    from generated_gallery import scan_all_items

    cfg = merge_pipeline_config(overrides)
    artifact_index = _build_artifact_index()
    missing: list[str] = []
    for item in scan_all_items():
        stem = str(item.get("id") or "").strip()
        if not stem:
            continue
        state = pipeline_item_state(
            stem,
            overrides=cfg,
            _artifact_index=artifact_index,
            _config=cfg,
        )
        if state.get("missing") or state.get("final_stale"):
            missing.append(stem)
    return missing


def count_items_needing_pipeline(
    *,
    overrides: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    now = time.time()
    cached_result = _BACKLOG_CACHE.get("result")
    if (
        not force
        and overrides is None
        and isinstance(cached_result, dict)
        and now - float(_BACKLOG_CACHE.get("cached_at") or 0.0) < _BACKLOG_TTL_SEC
    ):
        cached = dict(cached_result)
        cached["cached"] = True
        cached["stale"] = bool(_BACKLOG_CACHE.get("dirty"))
        cached["refreshing"] = _BACKLOG_REFRESH_LOCK.locked()
        return cached

    observed_generation = int(_BACKLOG_CACHE.get("generation") or 0)
    acquired = _BACKLOG_REFRESH_LOCK.acquire(blocking=False)
    if not acquired:
        if isinstance(cached_result, dict):
            cached = dict(cached_result)
            cached.update(
                {
                    "cached": True,
                    "stale": True,
                    "refreshing": True,
                }
            )
            return cached
        _BACKLOG_REFRESH_LOCK.acquire()
        acquired = True

    try:
        cached_result = _BACKLOG_CACHE.get("result")
        if (
            isinstance(cached_result, dict)
            and int(_BACKLOG_CACHE.get("generation") or 0)
            != observed_generation
        ):
            cached = dict(cached_result)
            cached.update(
                {
                    "cached": True,
                    "stale": False,
                    "refreshing": False,
                }
            )
            return cached

        now = time.time()
        if (
            not force
            and overrides is None
            and isinstance(cached_result, dict)
            and now - float(_BACKLOG_CACHE.get("cached_at") or 0.0)
            < _BACKLOG_TTL_SEC
        ):
            cached = dict(cached_result)
            cached.update(
                {
                    "cached": True,
                    "stale": bool(_BACKLOG_CACHE.get("dirty")),
                    "refreshing": False,
                }
            )
            return cached

        sig = _backlog_cache_signature(overrides)
        if (
            not force
            and overrides is None
            and _BACKLOG_CACHE.get("sig") == sig
            and isinstance(cached_result, dict)
        ):
            cached = dict(cached_result)
            cached.update(
                {
                    "cached": True,
                    "stale": False,
                    "refreshing": False,
                }
            )
            _BACKLOG_CACHE["cached_at"] = now
            _BACKLOG_CACHE["dirty"] = False
            return cached

        ids = list_items_needing_pipeline(overrides=overrides)
        result: dict[str, Any] = {
            "count": len(ids),
            "sample": ids[:8],
            "cached": False,
            "stale": False,
            "refreshing": False,
        }
        if overrides is None:
            _BACKLOG_CACHE["sig"] = sig
            _BACKLOG_CACHE["result"] = {
                "count": result["count"],
                "sample": result["sample"],
            }
            _BACKLOG_CACHE["cached_at"] = now
            _BACKLOG_CACHE["dirty"] = False
            _BACKLOG_CACHE["generation"] = (
                int(_BACKLOG_CACHE.get("generation") or 0) + 1
            )
        return result
    finally:
        if acquired:
            _BACKLOG_REFRESH_LOCK.release()


def _resolve_targets(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    if payload.get("image_id"):
        ids.append(str(payload["image_id"]))
    for raw in payload.get("image_ids") or []:
        ids.append(str(raw))
    group_id = payload.get("group_id")
    if group_id:
        from generated_gallery import get_group

        group = get_group(str(group_id))
        if group:
            for item in group.get("items") or []:
                if item.get("id"):
                    ids.append(str(item["id"]))
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        stem = Path(i).stem
        if stem not in seen:
            seen.add(stem)
            out.append(stem)
    return out


def start_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    overrides = payload.get("options") if isinstance(payload.get("options"), dict) else None
    only_missing = bool(
        payload.get("only_missing")
        or payload.get("all_missing")
        or payload.get("only_missing_all")
        or (isinstance(overrides, dict) and overrides.get("only_missing"))
    )
    if payload.get("all_missing") or payload.get("only_missing_all"):
        if isinstance(overrides, dict):
            overrides = {**overrides, "only_missing": True}
        else:
            overrides = {"only_missing": True}
        targets = list_items_needing_pipeline(overrides=overrides)
    else:
        targets = _resolve_targets(payload)
    if not targets:
        return {"ok": False, "message": "未指定图片或没有待补跑的后处理"}

    with _LOCK:
        if _JOB.get("status") == "running":
            return {"ok": False, "message": "已有流水线任务进行中", "job": dict(_JOB)}
        _JOB.clear()
        _JOB.update(
            {
                "status": "running",
                "message": "启动中…",
                "total": len(targets),
                "done": 0,
                "ok": 0,
                "fail": 0,
                "items": [],
                "cancel_requested": False,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            }
        )

    def _worker() -> None:
        import concurrent.futures
        workers = min(4, max(1, os.cpu_count() or 2))

        def _process_one(image_id: str) -> None:
            with _LOCK:
                if _JOB.get("cancel_requested"):
                    item = {"ok": False, "id": image_id, "message": "cancelled", "skipped": True}
                    _JOB["done"] += 1
                    _JOB["items"] = (_JOB.get("items") or [])[-19:] + [item]
                    return
                _JOB["message"] = f"处理 {image_id}…"
            try:
                result = process_image(
                    image_id,
                    overrides=overrides,
                    only_missing=only_missing,
                )
                item = {**result, "ok": True}
                ok = True
            except Exception as exc:
                item = {"ok": False, "id": image_id, "message": str(exc)}
                ok = False
            with _LOCK:
                _JOB["done"] += 1
                if ok:
                    _JOB["ok"] += 1
                else:
                    _JOB["fail"] += 1
                _JOB["items"] = (_JOB.get("items") or [])[-19:] + [item]

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_process_one, targets))

        with _LOCK:
            cancelled = bool(_JOB.get("cancel_requested"))
            _JOB["status"] = "cancelled" if cancelled else "idle"
            _JOB["message"] = (
                "已取消"
                if cancelled
                else f"完成：成功 {_JOB.get('ok', 0)}，失败 {_JOB.get('fail', 0)}"
            )
            _JOB["finished_at"] = datetime.now().isoformat(timespec="seconds")
        invalidate_backlog_cache()

    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True, "message": f"流水线已启动（{len(targets)} 张）", "total": len(targets)}


def maybe_auto_pipeline(filename: str) -> dict[str, Any] | None:
    cfg = load_config()
    if not cfg.get("auto_after_generate"):
        return None
    stem = Path(filename).stem
    try:
        return process_image(stem, only_missing=True)
    except Exception as exc:
        print(f"[pipeline] auto-after-generate failed for {stem}: {exc}", flush=True)
        return {"ok": False, "message": str(exc)}


def schedule_auto_pipeline(filename: str) -> None:
    """生图后后台跑后处理，避免阻塞 NAI 请求线程。"""
    cfg = load_config()
    if not cfg.get("auto_after_generate"):
        return

    def _worker() -> None:
        try:
            result = maybe_auto_pipeline(filename)
            if result and not result.get("ok"):
                print(
                    f"[pipeline] auto-after-generate skipped {filename}: {result.get('message')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[pipeline] auto-after-generate crashed for {filename}: {exc}", flush=True)

    threading.Thread(target=_worker, daemon=True, name=f"auto-pipe-{filename}").start()

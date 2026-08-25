"""Pixiv 起号流水线：AI 导演（人设 + 小作文）→ 后处理 → 上传 P 站。"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text
from local_secrets import protect_secret, unprotect_secret

from generated_gallery import get_group, group_key_for_item, list_groups, scan_all_items
from generated_layout import find_generated_file, resolve_png
from pixiv_accounts import (
    account_display_name,
    accounts_auth_status,
    get_active_account,
    get_active_account_id,
    update_account_profile,
    validate_account_for_upload,
    _find_account_by_pixiv_uid,
    _int_or_none,
)
from nai_char import prompt_snapshot_from_comment, prompt_snapshot_from_png
from pixiv_char_tags import collect_ark_char_pixiv_hints
from post_pipeline import (
    build_artifact_index,
    discover_anr_root,
    merge_pipeline_config,
    mosaic_runtime_status,
    pipeline_item_state,
    process_image,
)
from usage_ledger import record_usage

# --- 拆分模块回填（facade 再导出，保持 from pixiv_launch import X 兼容）---
from pixiv_launch_config import (
    CONFIG_PATH,
    DATA_DIR,
    DRAFT_PATH,
    GENERATED_DIR,
    HISTORY_PATH,
    LAST_JOB_PATH,
    PERSONA_SYSTEM,
    PIXIV_API_BASE,
    PIXIV_MAX_TAGS,
    POST_SYSTEM,
    PREPARED_ARCHIVE_DIR,
    PREPARED_PATH,
    ROOT,
    SECRET_PATH,
    _DEEPSEEK_ALLOWED_MODELS,
    _DEEPSEEK_DEFAULT_MODEL,
    _HISTORY_LOCK,
    _MODEL_TOKEN_RE,
    _PREPARED_LOCK,
    _STALE_AI_WARNING_MARKERS,
    _clean_stale_ai_warning,
    _ensure_upload_mosaic_policy,
    _looks_like_bad_model,
    _provider_preset,
    _read_ai_secret,
    _read_secret,
    ai_auth_status,
    load_config,
    normalize_ai_config,
    pixiv_auth_status,
    save_ai_key,
    save_config,
    save_pixiv_token,
)
from pixiv_ai_transport import (
    _ai_env,
    _chat_completion,
    _chat_response_text,
    _chat_url,
    _extract_json_block,
    _models_url,
    _vision_health_data_url,
    chat_json,
    list_ai_models,
    test_ai_connection,
    test_ai_vision_connection,
)
from pixiv_launch_tags import (
    _TAG_NOISE,
    _balance_upload_tags,
    _collect_bilingual_hints,
    _is_pipeline_noise_tag,
    _load_tag_lexicon,
    _local_persona,
    _looks_chinese_tag,
    _looks_japanese_tag,
    _mapping_zh_ja,
    _normalize_tag_token,
    _prompt_text_from_snapshot,
    _read_png_text_tags,
    _resolve_prompt_snapshot,
    _split_tags,
    _tag_hints_from_prompt,
    _tags_from_caption_text,
    _tags_from_pipeline_meta_cfg,
    _tags_from_prompt_snapshot,
)






_logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_JOB: dict[str, Any] = {
    "status": "idle",
    "message": "空闲",
    "step": "",
    "progress": {"current": 0, "total": 0, "percent": 0, "label": ""},
    "result": None,
}
_LAST_JOB_REQUEST: dict[str, Any] = {}


def launch_status() -> dict[str, Any]:
    with _LOCK:
        return copy.deepcopy(_JOB)


def _remember_job_request(kind: str, payload: dict[str, Any]) -> None:
    request = {
        "kind": kind,
        "payload": copy.deepcopy(payload),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    with _LOCK:
        _LAST_JOB_REQUEST.clear()
        _LAST_JOB_REQUEST.update(request)
    try:
        atomic_write_text(
            LAST_JOB_PATH,
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        _logger.warning("无法写入最近任务请求记录 %s: %s", LAST_JOB_PATH, exc)


def _load_last_job_request() -> dict[str, Any]:
    with _LOCK:
        if _LAST_JOB_REQUEST:
            return copy.deepcopy(_LAST_JOB_REQUEST)
    if not LAST_JOB_PATH.exists():
        return {}
    try:
        data = json.loads(LAST_JOB_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("payload"), dict):
            return {}
        return copy.deepcopy(data)
    except Exception:
        return {}


def _review_state_for_failures(failures: list[dict[str, Any]]) -> tuple[int, int]:
    pending = 0
    reviewed = 0
    cfg = load_config()
    overrides = _upload_pipeline_overrides(cfg)
    for failure in failures:
        image_id = str(failure.get("id") or failure.get("image_id") or "").strip()
        if not image_id:
            continue
        state = pipeline_item_state(Path(image_id).stem, overrides=overrides)
        manual_status = str(state.get("manual_status") or "").strip().lower()
        if manual_status in {"approved", "excluded"}:
            reviewed += 1
        else:
            pending += 1
    return pending, reviewed


def resume_last_job_after_review() -> dict[str, Any]:
    with _LOCK:
        status = str(_JOB.get("status") or "")
        failures = copy.deepcopy(_JOB.get("pipeline_failures") or [])
        if not failures and isinstance(_JOB.get("result"), dict):
            failures = copy.deepcopy((_JOB.get("result") or {}).get("pipeline_failures") or [])
    request = _load_last_job_request()

    if status == "running":
        return {"ok": True, "resumed": False, "message": "任务已在运行", "job": launch_status()}
    if status != "error":
        return {"ok": True, "resumed": False, "message": "当前没有等待恢复的失败任务"}
    if not request:
        return {"ok": False, "resumed": False, "message": "没有可继续的上传任务"}
    if not failures:
        return {"ok": True, "resumed": False, "message": "当前失败任务没有待审查图片"}
    if failures:
        pending, reviewed = _review_state_for_failures(failures)
        if pending:
            return {
                "ok": True,
                "resumed": False,
                "pending": pending,
                "reviewed": reviewed,
                "message": f"还有 {pending} 张待人工审查",
            }

    kind = str(request.get("kind") or "")
    payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
    if kind == "upload":
        result = start_upload_job(payload)
    elif kind == "launch":
        result = launch_one_click(payload)
    else:
        return {"ok": False, "resumed": False, "message": "上次任务类型未知，不能继续"}

    return {
        "ok": bool(result.get("ok")),
        "resumed": bool(result.get("ok")),
        "message": result.get("message") or ("已继续上传" if result.get("ok") else "继续失败"),
        "result": result,
    }


def _job_progress(
    *,
    current: int,
    total: int,
    label: str,
    step: str | None = None,
    message: str | None = None,
) -> None:
    total = max(0, int(total or 0))
    current = max(0, min(int(current or 0), total if total else int(current or 0)))
    percent = round((current / total) * 100, 1) if total else 0
    with _LOCK:
        if step is not None:
            _JOB["step"] = step
        if message is not None:
            _JOB["message"] = message
        _JOB["progress"] = {
            "current": current,
            "total": total,
            "percent": percent,
            "label": label,
        }




def _upload_require_processed(cfg: dict[str, Any] | None) -> bool:
    # Upload must never fall back to the raw generated PNG. The processed
    # variant is where mandatory mosaic and metadata stripping are enforced.
    return True


def _resolve_upload_paths(
    image_ids: list[str],
    cfg: dict[str, Any] | None = None,
    *,
    require_processed: bool | None = None,
) -> list[Path]:
    if require_processed is None:
        require_processed = _upload_require_processed(cfg)
    out: list[Path] = []
    for image_id in image_ids:
        stem = Path(str(image_id or "")).stem
        if not stem:
            continue
        final_path = resolve_png(f"{stem}_final.png", root=GENERATED_DIR)
        if cfg and require_processed:
            _assert_pipeline_ready(stem, cfg)
        if final_path.exists():
            out.append(final_path)
            continue
        if require_processed:
            raise FileNotFoundError(
                f"图片 {stem} 尚未完成后处理，缺少 {final_path.name}。"
                "请先在生成图库跑流水线，或开启「上传前自动后处理」。"
            )
        source = resolve_png(f"{stem}.png", root=GENERATED_DIR)
        if not source.exists():
            raise FileNotFoundError(f"图片不存在: {image_id}")
        out.append(source)
    if not out:
        raise FileNotFoundError("未找到可上传的图片")
    return out


def _ordered_image_ids(raw_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in raw_ids:
        stem = Path(str(raw or "")).stem
        if stem and stem not in seen:
            seen.add(stem)
            ordered.append(stem)
    return ordered


def _image_ids_for_group(group_id: str) -> list[str]:
    group = get_group(group_id)
    if not group:
        raise FileNotFoundError(f"生成系列不存在: {group_id}")
    items = sorted(
        group.get("items") or [],
        key=lambda x: str(x.get("created_at") or ""),
    )
    raw = [str(item["id"]) for item in items if item.get("id")]
    ordered = _ordered_image_ids(raw)
    if not ordered:
        raise FileNotFoundError(f"系列 {group_id} 无可用图片")
    return ordered


def _resolve_selection(payload: dict[str, Any]) -> tuple[list[str], str]:
    """解析起号/上传目标：单张、多张或整组系列（系列=全部 *_final.png，按生成时间正序）。"""
    batches = _resolve_selection_batches(payload)
    batch = batches[0]
    group_id = str(batch.get("group_id") or "").strip()
    image_ids = list(batch.get("image_ids") or [])
    primary = image_ids[0]
    return image_ids, group_id or primary


def _resolve_selection_batches(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """解析上传批次；多系列默认合并为一篇多页投稿（merge_groups=false 时各系列分开投）。"""
    raw_series = payload.get("series")
    if isinstance(raw_series, list) and raw_series:
        batches: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_series):
            if not isinstance(raw, dict):
                raise ValueError(f"series[{index}] 必须是对象")
            image_ids = _ordered_image_ids(list(raw.get("image_ids") or []))
            if not image_ids:
                raise ValueError(f"series[{index}] 没有图片")
            group_id = str(raw.get("group_id") or image_ids[0]).strip()[:120]
            batches.append(
                {
                    "group_id": group_id,
                    "group_ids": [group_id],
                    "image_ids": image_ids,
                    "merged": False,
                }
            )
        return batches
    raw_groups = payload.get("group_ids")
    if isinstance(raw_groups, list) and raw_groups:
        gids = [str(raw or "").strip() for raw in raw_groups if str(raw or "").strip()]
        if not gids:
            raise ValueError("group_ids 为空")
        merge_groups = payload.get("merge_groups", True) is not False
        if merge_groups and len(gids) > 1:
            merged_ids: list[str] = []
            for gid in gids:
                merged_ids.extend(_image_ids_for_group(gid))
            ordered = _ordered_image_ids(merged_ids)
            return [
                {
                    "group_id": "+".join(gids),
                    "group_ids": gids,
                    "image_ids": ordered,
                    "merged": True,
                }
            ]
        batches: list[dict[str, Any]] = []
        for gid in gids:
            batches.append(
                {"group_id": gid, "image_ids": _image_ids_for_group(gid)}
            )
        return batches

    ids: list[str] = []
    group_id = str(payload.get("group_id") or "").strip()
    if group_id and "+" in group_id:
        gids = [part.strip() for part in group_id.split("+") if part.strip()]
        if len(gids) > 1:
            explicit_ids = [
                str(raw or "").strip()
                for raw in (payload.get("image_ids") or [])
                if str(raw or "").strip()
            ]
            ordered = _ordered_image_ids(explicit_ids)
            if not ordered:
                merged_ids: list[str] = []
                for gid in gids:
                    merged_ids.extend(_image_ids_for_group(gid))
                ordered = _ordered_image_ids(merged_ids)
            if not ordered:
                raise FileNotFoundError(f"合并系列无可用图片: {group_id}")
            if payload.get("merge_groups", True) is not False:
                return [
                    {
                        "group_id": "+".join(gids),
                        "group_ids": gids,
                        "image_ids": ordered,
                        "merged": True,
                    }
                ]
            return [
                {"group_id": gid, "image_ids": _image_ids_for_group(gid)}
                for gid in gids
            ]
    if group_id:
        ids = _image_ids_for_group(group_id)
    else:
        image_id = str(payload.get("image_id") or "").strip()
        if image_id:
            ids.append(image_id)
        for raw in payload.get("image_ids") or []:
            ids.append(str(raw))
        ids = _ordered_image_ids(ids)
    if not ids:
        raise ValueError("请指定 image_id、image_ids、group_id 或 group_ids")
    primary = ids[0]
    return [
        {
            "group_id": group_id or primary,
            "image_ids": ids,
        }
    ]


def _pipeline_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """起号页 pipeline 配置覆盖全局 post_pipeline.json。"""
    pipe = (cfg.get("pipeline") or {}) if isinstance(cfg.get("pipeline"), dict) else {}
    overrides: dict[str, Any] = {
        "only_missing": pipe.get("only_missing", True),
        "anr_root": pipe.get("anr_root") or "",
    }
    for block in ("upscale", "mosaic", "metadata"):
        if isinstance(pipe.get(block), dict):
            overrides[block] = dict(pipe[block])
    return overrides


def _upload_pipeline_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """上传链路专用：强制开启打码，忽略用户关闭打码的配置。"""
    overrides = _pipeline_overrides(_ensure_upload_mosaic_policy(cfg))
    mosaic = dict(overrides.get("mosaic") or DEFAULTS["pipeline"]["mosaic"])
    mosaic["enabled"] = True
    overrides["mosaic"] = mosaic
    overrides["metadata"] = {
        "enabled": True,
        "custom_note": "",
        "custom_note_key": "",
        "png_text": {},
        "pipeline_marker": False,
    }
    return overrides


def _ensure_mosaic_runtime_for_upload(cfg: dict[str, Any]) -> None:
    overrides = _upload_pipeline_overrides(cfg)
    runtime = mosaic_runtime_status(merge_pipeline_config(overrides))
    if not runtime.get("ok"):
        raise RuntimeError(
            str(runtime.get("message") or "打码环境未就绪")
            + "。上传前必须打码，请检查 post_pipeline.json 的 anr_root 与本机 ANR 依赖。"
        )


def _assert_pipeline_ready(stem: str, cfg: dict[str, Any]) -> None:
    """上传前校验：即使已有 *_final.png，打码等缺失仍应拦截。"""
    overrides = _upload_pipeline_overrides(cfg)
    state = pipeline_item_state(stem, overrides=overrides)
    if state.get("excluded"):
        raise RuntimeError(f"图片 {stem} 已被人工剔除")
    if state.get("manual_status") == "approved" and state.get("final"):
        return
    if not state.get("mosaic"):
        skip = str(state.get("mosaic_skip") or "")
        extra = ""
        if skip:
            reason = skip.replace("mosaic:skip(", "").rstrip(")")
            extra = f"（打码曾失败：{reason}）"
        raise RuntimeError(
            f"图片 {stem} 上传前必须完成打码{extra}。"
            "请在 Pixiv 起号页 ⑤ 后处理或生成图库「本组一键处理」补跑后再上传。"
        )
    if state.get("final_stale"):
        raise RuntimeError(
            f"图片 {stem} 的 *_final.png 与后处理产物不同步（可能是旧文件）。"
            "请在 Pixiv 起号页 ⑤ 后处理或生成图库「本组一键处理」重跑后再上传。"
        )
    missing = [str(x) for x in (state.get("missing") or []) if x != "mosaic_failed"]
    if not missing:
        return
    skip = str(state.get("mosaic_skip") or "")
    extra = ""
    if skip:
        reason = skip.replace("mosaic:skip(", "").rstrip(")")
        extra = f"（打码曾失败：{reason}）"
    raise RuntimeError(
        f"图片 {stem} 后处理未齐全，缺少：{'、'.join(missing)}{extra}。"
        "请在 Pixiv 起号页 ⑤ 后处理或生成图库「本组一键处理」补跑后再上传。"
    )


def _maybe_pipeline(
    image_id: str,
    cfg: dict[str, Any],
    *,
    for_upload: bool = False,
) -> dict[str, Any] | None:
    upload_cfg = cfg.get("upload") or {}
    if not upload_cfg.get("auto_pipeline", True):
        return None
    stem = Path(image_id).stem
    overrides = _upload_pipeline_overrides(cfg) if for_upload else _pipeline_overrides(cfg)
    only_missing = bool(overrides.get("only_missing", True))
    state = pipeline_item_state(stem, overrides=overrides)
    if only_missing and not state.get("missing") and not state.get("final_stale"):
        final_url = state.get("processed_url") or ""
        if not final_url and state.get("final"):
            final_url = f"/data/generated/{stem}_final.png"
        return {
            "ok": True,
            "skipped": True,
            "final_url": final_url,
            "steps": state.get("steps") or [],
            "message": "后处理步骤已齐全",
        }
    return process_image(stem, overrides=overrides, only_missing=only_missing)






def _fetch_work_context(work_id: int | None) -> dict[str, Any]:
    if not work_id:
        return {}
    try:
        from paths import normalize_config, project_root

        root = project_root()
        raw_cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
        cfg = normalize_config(raw_cfg, root)
        from db import Database

        with Database(Path(cfg["data_dir"]) / "aitag.db") as db:
            detail = db.get_work_detail(int(work_id)) or {}
        work = detail.get("work") or {}
        images = detail.get("images") or []
        prompt_text = ""
        for img in images:
            prompt_text = str(img.get("prompt_text") or img.get("ai_json") or "").strip()
            if prompt_text:
                break
        work_tags_raw = str(work.get("tags") or "").strip()
        source_tags = _split_tags(work_tags_raw)
        for t in _split_tags(prompt_text):
            if t not in source_tags:
                source_tags.append(t)
        return {
            "work_title": str(work.get("title") or work.get("caption") or "").strip(),
            "work_tags": work_tags_raw,
            "source_tags": source_tags[:80],
            "prompt_text": prompt_text[:1200],
            "tag_hints": _tag_hints_from_prompt(prompt_text or work_tags_raw, source_tags),
        }
    except Exception:
        return {}


def _build_image_context(image_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx: dict[str, Any] = {"image_id": image_id}
    if not image_id:
        return ctx
    stem = Path(image_id).stem
    meta_path = find_generated_file(f"{stem}.png.meta.json", root=GENERATED_DIR)
    if meta_path is None:
        png = find_generated_file(f"{stem}.png", root=GENERATED_DIR)
        if png is not None:
            from generated_layout import sidecar_path_for

            meta_path = sidecar_path_for(png, f"{stem}.png.meta.json")
        else:
            meta_path = GENERATED_DIR / f"{stem}.png.meta.json"
    if meta_path.exists():
        try:
            ctx.update(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    work_ctx = _fetch_work_context(ctx.get("work_id"))
    cfg = cfg or load_config()
    pipe_meta = ((cfg.get("pipeline") or {}).get("metadata") or {})

    patched_tags: list[str] = []
    snapshot = _resolve_prompt_snapshot(ctx, stem)
    if snapshot:
        ctx["prompt_snapshot"] = snapshot
    patched_prompt = _prompt_text_from_snapshot(snapshot)
    patched_tags.extend(_tags_from_prompt_snapshot(snapshot))
    patched_tags.extend(_tags_from_pipeline_meta_cfg(pipe_meta))
    if not (patched_prompt or patched_tags):
        source_png = resolve_png(f"{stem}.png", root=GENERATED_DIR)
        if source_png.exists():
            for t in _read_png_text_tags(source_png):
                if t not in patched_tags:
                    patched_tags.append(t)

    patched_tags = list(
        dict.fromkeys([t for t in patched_tags if t and not _is_pipeline_noise_tag(t)])
    )[:80]

    if patched_tags or patched_prompt:
        ctx["source_tags"] = patched_tags
        ctx["prompt_text"] = patched_prompt or ", ".join(patched_tags[:40])
        ctx["work_tags"] = ", ".join(patched_tags[:40])
        zh_hints, ja_hints = _collect_bilingual_hints(
            ctx["prompt_text"],
            patched_tags,
        )
        ctx["tag_hints_zh"] = zh_hints
        ctx["tag_hints_ja"] = ja_hints
        ctx["tag_hints"] = _balance_upload_tags([], zh_hints, ja_hints, [])
        ctx["tag_source"] = "generation_snapshot"
    else:
        ctx.update(work_ctx)
        zh_hints, ja_hints = _collect_bilingual_hints(
            str(ctx.get("prompt_text") or ""),
            list(ctx.get("source_tags") or []),
        )
        ctx["tag_hints_zh"] = zh_hints
        ctx["tag_hints_ja"] = ja_hints
        ctx["tag_hints"] = _balance_upload_tags([], zh_hints, ja_hints, [])
        ctx["tag_source"] = "work_db"

    if not str(ctx.get("work_title") or "").strip() and work_ctx.get("work_title"):
        ctx["work_title"] = work_ctx["work_title"]
    return ctx


def _ensure_pipelines(
    image_ids: list[str],
    cfg: dict[str, Any],
    *,
    force: bool = False,
) -> list[str]:
    """上传/写文案前：未过后处理的图自动补跑流水线。"""
    upload_cfg = cfg.get("upload") or {}
    if not force and not upload_cfg.get("auto_pipeline", True):
        return []
    ran: list[str] = []
    for image_id in image_ids:
        result = _maybe_pipeline(image_id, cfg, for_upload=force)
        if result and not result.get("skipped"):
            ran.append(image_id)
    return ran


def _ensure_upload_ready(
    image_ids: list[str],
    cfg: dict[str, Any],
    *,
    progress_label: str = "上传前处理",
    skip_failed: bool = False,
) -> list[str]:
    """上传前强制完成后处理，并确保 *_final.png 已产出。"""
    _ensure_mosaic_runtime_for_upload(cfg)
    total = len(image_ids)
    _job_progress(
        current=0,
        total=total,
        label=progress_label,
        step="pipeline",
        message=f"{progress_label}：准备检查 {total} 张图…",
    )
    ran: list[str] = []
    ready: list[str] = []
    failures: list[dict[str, str]] = []
    overrides = _upload_pipeline_overrides(cfg)
    for idx, image_id in enumerate(image_ids, start=1):
        stem = Path(image_id).stem
        final_path = resolve_png(f"{stem}_final.png", root=GENERATED_DIR)
        try:
            state = pipeline_item_state(stem, overrides=overrides)
            if state.get("excluded"):
                raise RuntimeError("已被人工剔除")
            _job_progress(
                current=idx - 1,
                total=total,
                label=progress_label,
                step="pipeline",
                message=f"{progress_label}：第 {idx}/{total} 张，补跑打码/清元数据…",
            )
            if state.get("manual_status") == "approved" and final_path.exists():
                ready.append(image_id)
            elif state.get("missing") or state.get("final_stale"):
                result = process_image(
                    stem,
                    overrides=overrides,
                    only_missing=not state.get("final_stale")
                    and bool(overrides.get("only_missing", True)),
                )
                if not result.get("ok"):
                    raise RuntimeError(f"后处理失败: {image_id}")
                if image_id not in ran and not result.get("skipped"):
                    ran.append(image_id)
            elif not final_path.exists():
                result = process_image(stem, overrides=overrides, only_missing=False)
                if not result.get("ok"):
                    raise RuntimeError(f"后处理失败: {image_id}")
                if image_id not in ran:
                    ran.append(image_id)
            _assert_pipeline_ready(stem, cfg)
            if not final_path.exists():
                raise FileNotFoundError(
                    f"后处理未产出 {final_path.name}，无法上传原图版本: {image_id}"
                )
            ready.append(image_id)
            _job_progress(
                current=idx,
                total=total,
                label=progress_label,
                step="pipeline",
                message=f"{progress_label}：第 {idx}/{total} 张完成",
            )
        except Exception as exc:
            if not skip_failed:
                raise
            failure = {"id": image_id, "message": str(exc)}
            failures.append(failure)
            with _LOCK:
                current = list(_JOB.get("pipeline_failures") or [])
                _JOB["pipeline_failures"] = current + [failure]
            _job_progress(
                current=idx,
                total=total,
                label=progress_label,
                step="pipeline",
                message=f"{progress_label}：第 {idx}/{total} 张失败，已跳过：{exc}",
            )
            continue
    if skip_failed:
        return ready
    return ran


def _merge_tags(post: dict[str, Any], image_ctx: dict[str, Any], defaults: list[str]) -> None:
    post["tags"] = _balance_upload_tags(
        list(post.get("tags") or []),
        list(image_ctx.get("tag_hints_zh") or []),
        list(image_ctx.get("tag_hints_ja") or []),
        list(defaults or []),
    )


def _local_post(
    persona: dict[str, Any],
    image_ctx: dict[str, Any],
    extra: str = "",
) -> dict[str, Any]:
    name = persona.get("account_name_suggestion") or "今日摸鱼"
    defaults = list(persona.get("tag_strategy") or DEFAULTS["account"]["default_tags"])
    tags = _balance_upload_tags(
        [],
        list(image_ctx.get("tag_hints_zh") or []),
        list(image_ctx.get("tag_hints_ja") or []),
        defaults,
        max_tags=PIXIV_MAX_TAGS,
    )
    subject = image_ctx.get("work_title") or "摸鱼存档"
    caption_zh = (
        f"久违地摸了一张《{subject}》。\n\n"
        f"这次想试试更柔和的光线和更干净的构图，"
        f"{'补了一句：' + extra if extra else '让角色情绪再安静一点。'}\n\n"
        f"如果喜欢的话欢迎点赞与收藏。"
    )
    return {
        "title": f"{name} · {subject[:10]}",
        "title_ja": f"{name} · 落書き",
        "title_zh": f"{name} · {subject[:12]}",
        "caption": caption_zh,
        "caption_ja": "久しぶりに一枚描きました。柔らかい光と静かな雰囲気を意識しています。",
        "caption_zh": caption_zh,
        "tags": tags,
        "alt_titles": [f"今日份{name}", "摸鱼小记"],
        "source": "local_fallback",
    }


def _normalize_director_post(raw: dict[str, Any]) -> dict[str, Any]:
    title_ja = str(raw.get("title_ja") or raw.get("title") or "").strip()
    title_zh = str(raw.get("title_zh") or "").strip()
    cap_ja = str(raw.get("caption_ja") or "").strip()
    cap_zh = str(raw.get("caption_zh") or raw.get("caption") or "").strip()
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[\s,，]+", tags) if t.strip()]
    title = title_ja or title_zh or "无题"
    parts = [p for p in (cap_ja, cap_zh) if p]
    caption = "\n\n".join(parts) if parts else cap_zh or cap_ja
    return {
        "title": title,
        "title_ja": title_ja,
        "title_zh": title_zh,
        "caption": caption,
        "caption_ja": cap_ja,
        "caption_zh": cap_zh,
        "tags": [str(t).strip() for t in tags if str(t).strip()],
        "alt_titles": list(raw.get("alt_titles") or [])[:2],
    }


def generate_persona(
    *,
    direction: str = "",
    nickname_hint: str = "",
    save: bool = True,
) -> dict[str, Any]:
    cfg = load_config()
    account = cfg.get("account") or {}
    active = get_active_account() or {}
    direction = str(
        direction or active.get("direction") or account.get("direction") or ""
    ).strip()
    nickname_hint = str(nickname_hint or account.get("nickname_hint") or "").strip()
    env = _ai_env(cfg)

    if not direction:
        direction = "AI 生成图爱好者，分享 NovelAI 同人插画"

    payload = {
        "direction": direction,
        "nickname_hint": nickname_hint,
        "style": account.get("style", ""),
        "language": account.get("language", "zh"),
        "nsfw_level": account.get("nsfw_level", "sfw"),
    }

    try:
        if env["api_key"] and env["model"]:
            text = _chat_completion(env, PERSONA_SYSTEM, payload)
            persona = _extract_json_block(text)
            persona["source"] = "ai"
        else:
            persona = _local_persona(direction, nickname_hint)
    except Exception as exc:
        persona = _local_persona(direction, nickname_hint)
        persona["warning"] = f"AI 人设生成失败，已用本地模板：{exc}"

    if save:
        cfg = save_config(
            {
                "account": {
                    "direction": direction,
                    "nickname_hint": nickname_hint,
                    "persona": persona,
                }
            }
        )
        aid = get_active_account_id()
        if aid:
            update_account_profile(aid, direction=direction, persona=persona)
    return {"ok": True, "persona": persona, "config": cfg if save else load_config()}


def generate_post_copy(
    *,
    image_id: str = "",
    extra: str = "",
    persona: dict[str, Any] | None = None,
    save_draft: bool = True,
    run_pipeline: bool = True,
) -> dict[str, Any]:
    cfg = load_config()
    account = cfg.get("account") or {}
    active = get_active_account() or {}
    persona = persona or active.get("persona") or account.get("persona") or {}
    if not persona:
        gen = generate_persona(save=True)
        persona = gen["persona"]

    pipeline_ran: list[str] = []
    if run_pipeline and image_id:
        pipeline_ran = _ensure_pipelines([image_id], cfg)

    image_ctx = _build_image_context(image_id, cfg)
    env = _ai_env(cfg)
    warning = ""
    payload = {
        "persona": persona,
        "image_context": image_ctx,
        "source_tags": image_ctx.get("source_tags") or [],
        "tag_hints_zh": image_ctx.get("tag_hints_zh") or [],
        "tag_hints_ja": image_ctx.get("tag_hints_ja") or [],
        "tag_source": image_ctx.get("tag_source") or "",
        "tag_policy": f"中文为主 + 日文检索 tag，共最多 {PIXIV_MAX_TAGS} 个（Pixiv 上限）",
        "user_extra": str(extra or "").strip(),
        "default_tags": account.get("default_tags") or [],
        "nsfw_level": account.get("nsfw_level", "sfw"),
    }
    try:
        if env["api_key"] and env["model"]:
            text = _chat_completion(env, POST_SYSTEM, payload)
            post = _normalize_director_post(_extract_json_block(text))
            post["source"] = "ai_director"
        else:
            post = _local_post(persona, image_ctx, extra)
    except Exception as exc:
        post = _local_post(persona, image_ctx, extra)
        warning = f"AI 导演失败，已用本地模板：{exc}"

    if isinstance(post.get("tags"), str):
        post["tags"] = [t for t in re.split(r"[\s,，]+", post["tags"]) if t.strip()]
    _merge_tags(post, image_ctx, list(account.get("default_tags") or []))
    if warning:
        post["warning"] = warning

    if save_draft:
        draft = {
            "image_id": image_id,
            "post": post,
            "persona": persona,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_write_text(
            DRAFT_PATH,
            json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "ok": True,
        "post": post,
        "persona": persona,
        "pipeline_ran": pipeline_ran,
        "tag_source": image_ctx.get("tag_source") or "",
    }


def load_prepared_submission(package_id: str = "") -> dict[str, Any]:
    """Return the latest upload-ready package without exposing account secrets."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(package_id or ""))[:80]
    source = PREPARED_ARCHIVE_DIR / f"{safe_id}.json" if safe_id else PREPARED_PATH
    with _PREPARED_LOCK:
        if not source.exists():
            return {"ok": True, "prepared": None}
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except Exception:
            return {"ok": True, "prepared": None}
    return {"ok": True, "prepared": data if isinstance(data, dict) else None}


def prepare_submission_package(payload: dict[str, Any]) -> dict[str, Any]:
    """Finish processing and copywriting, then stop before the Pixiv upload.

    This is the safe automation boundary used by the gallery butler: generated
    files and post copy are made ready, but no Pixiv upload API/browser action
    is invoked.
    """
    batches = _resolve_selection_batches(payload)
    has_explicit_group = bool(
        payload.get("group_id") or payload.get("group_ids") or payload.get("series")
    )
    cfg = load_config()
    account = cfg.get("account") or {}
    persona = account.get("persona") or {}
    if not persona:
        persona = generate_persona(save=True).get("persona") or {}

    total_images = sum(len(batch.get("image_ids") or []) for batch in batches)
    if total_images > 200:
        raise ValueError("单个投稿准备包最多 200 张图片")

    prepared_items: list[dict[str, Any]] = []
    extra = str(payload.get("extra") or "").strip()
    for index, batch in enumerate(batches):
        image_ids = list(batch.get("image_ids") or [])
        if not image_ids:
            continue
        # A Submission Draft promises upload-ready files regardless of the
        # ordinary auto-after-generate preference. This call raises on any
        # missing or stale final artifact and never uploads.
        _ensure_upload_ready(
            image_ids,
            cfg,
            progress_label=f"投稿准备 {index + 1}/{len(batches)}",
            skip_failed=False,
        )
        ready_ids = image_ids

        copy_extra = [extra]
        if batch.get("merged"):
            copy_extra.append(
                f"这是 {len(batch.get('group_ids') or [])} 个生成系列合并的"
                f" {len(ready_ids)} 页投稿，请写能概括整组的标题与简介。"
            )
        elif len(ready_ids) > 1:
            copy_extra.append(f"这是同一系列的 {len(ready_ids)} 页投稿。")
        copy_result = generate_post_copy(
            image_id=ready_ids[0],
            extra=" ".join(part for part in copy_extra if part),
            persona=persona,
            save_draft=True,
            run_pipeline=False,
        )
        post = copy_result.get("post") or {}
        tags = list(post.get("tags") or [])[:PIXIV_MAX_TAGS]
        prepared_items.append(
            {
                "group_id": str(batch.get("group_id") or "") if has_explicit_group else "",
                "group_ids": list(batch.get("group_ids") or []) if has_explicit_group else [],
                "image_id": ready_ids[0],
                "image_ids": ready_ids,
                "image_count": len(ready_ids),
                "post": post,
                "restrict": int((cfg.get("upload") or {}).get("restrict") or 0),
                "x_restrict": _resolve_x_restrict(tags, cfg),
                "illust_type": int((cfg.get("upload") or {}).get("illust_type") or 0),
                "pipeline_ready": True,
            }
        )

    if not prepared_items:
        raise ValueError("没有可准备的生成图片")
    package_id = re.sub(r"[^A-Za-z0-9_-]", "", str(payload.get("package_id") or ""))[:80]
    prepared = {
        "package_id": package_id,
        "status": "ready_for_upload",
        "prepared_at": datetime.now().isoformat(timespec="seconds"),
        "items": prepared_items,
        "total_images": sum(item["image_count"] for item in prepared_items),
        "upload_started": False,
        "pixiv_url": (
            f"/pixiv?prepared=1&package={package_id}"
            if package_id
            else "/pixiv?prepared=1"
        ),
    }
    serialized = json.dumps(prepared, ensure_ascii=False, indent=2) + "\n"
    with _PREPARED_LOCK:
        PREPARED_PATH.parent.mkdir(parents=True, exist_ok=True)
        latest_tmp = PREPARED_PATH.with_name(f"{PREPARED_PATH.name}.tmp")
        latest_tmp.write_text(serialized, encoding="utf-8")
        latest_tmp.replace(PREPARED_PATH)
        if package_id:
            PREPARED_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            archive_path = PREPARED_ARCHIVE_DIR / f"{package_id}.json"
            archive_tmp = archive_path.with_name(f"{archive_path.name}.tmp")
            archive_tmp.write_text(serialized, encoding="utf-8")
            archive_tmp.replace(archive_path)
    return {"ok": True, "prepared": prepared, "message": "投稿素材已准备完成，等待你检查并上传"}


def load_post_draft(primary_id: str, related_ids: list[str] | None = None) -> dict[str, Any]:
    """公开封装：供路由层读取与指定图片匹配的投稿草稿。"""
    return _load_post_draft(primary_id, related_ids)


def _load_post_draft(
    primary_id: str,
    related_ids: list[str] | None = None,
) -> dict[str, Any]:
    """读取 AI 导演已生成的投稿草稿（pixiv_draft.json）。"""
    if not DRAFT_PATH.exists():
        return {}
    try:
        raw = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        draft_image = str(raw.get("image_id") or "")
        related = {str(x) for x in (related_ids or []) if x}
        if draft_image != str(primary_id or "") and draft_image not in related:
            return {}
        post = raw.get("post")
        return post if isinstance(post, dict) else {}
    except Exception:
        return {}


def _resolve_x_restrict(tags: list[str], cfg: dict[str, Any] | None = None) -> str:
    """解析 Pixiv 网页端 R-18 分级：general / r18 / r18g。默认 r18 降低误封风险。"""
    cfg = cfg or load_config()
    upload_cfg = cfg.get("upload") or {}
    explicit = str(upload_cfg.get("x_restrict") or "").strip().lower()
    if explicit in ("general", "r18", "r18g"):
        return explicit
    joined = " ".join(str(t) for t in tags).lower()
    if "r18g" in joined or "r-18g" in joined:
        return "r18g"
    return "r18"


def _upload_pixiv_illust(
    image_paths: list[Path] | Path,
    *,
    title: str,
    caption: str,
    tags: list[str],
    restrict: int = 0,
    illust_type: int | None = None,
    ai_type: int | None = 1,
    x_restrict: str = "",
    account_id: str = "",
) -> dict[str, Any]:
    if isinstance(image_paths, Path):
        paths = [image_paths]
    else:
        paths = list(image_paths)
    if not paths:
        raise ValueError("未指定上传图片")

    # 账号在任务启动时已由前端确认并随 payload 钉死；上传中途切号不改变本次投稿目标
    pinned_account = str(account_id or "").strip() or get_active_account_id()
    upload_acc = validate_account_for_upload(pinned_account)
    upload_account_id = str(upload_acc.get("account_id") or pinned_account)
    user = upload_acc.get("user") or {}

    from pixiv_web_upload import (
        PixivWebUploadError,
        set_upload_progress_hook,
        upload_illust_via_web_sync,
    )

    cfg = load_config()
    upload_cfg = cfg.get("upload") or {}
    headless = bool(upload_cfg.get("browser_headless", False))
    resolved_x_restrict = str(x_restrict or "").strip().lower() or _resolve_x_restrict(tags, cfg)

    def _on_progress(msg: str) -> None:
        with _LOCK:
            if _JOB.get("status") == "running":
                _JOB["message"] = msg
                progress = dict(_JOB.get("progress") or {})
                progress["label"] = "浏览器投稿"
                if not progress.get("percent"):
                    progress["percent"] = 0
                _JOB["progress"] = progress

    set_upload_progress_hook(_on_progress)
    try:
        try:
            web_result = upload_illust_via_web_sync(
                paths,
                title=title,
                caption=caption,
                tags=tags,
                restrict=restrict,
                x_restrict=resolved_x_restrict,
                ai_type=ai_type,
                headless=headless,
                account_id=upload_account_id,
                expected_uid=(
                    int(uid)
                    if (uid := upload_acc.get("pixiv_user_id") or user.get("id")) not in (None, "")
                    and str(uid).isdigit()
                    else None
                ),
                expected_label=str(upload_acc.get("label") or account_display_name(upload_account_id)),
            )
        except PixivWebUploadError:
            raise
        except Exception as exc:
            raise RuntimeError(
                "网页投稿失败。"
                "请确认曾用浏览器登录过 Pixiv（通行密钥/邮箱），且 Chrome 可用。"
                f" 详情：{exc}"
            ) from exc
    finally:
        set_upload_progress_hook(None)

    illust_id = web_result.get("illust_id")
    record = {
        "illust_id": illust_id,
        "title": title,
        "caption": caption,
        "tags": tags,
        "image": paths[0].name,
        "images": [p.name for p in paths],
        "page_count": len(paths),
        "account_id": upload_account_id,
        "account_label": account_display_name(upload_account_id),
        "user_id": user.get("id"),
        "user_name": user.get("name") or user.get("account"),
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "pixiv_url": web_result.get("pixiv_url")
        or (f"https://www.pixiv.net/artworks/{illust_id}" if illust_id else ""),
        "upload_method": "web",
        "x_restrict": resolved_x_restrict,
    }
    _append_history(record)
    return record


def _append_history(record: dict[str, Any]) -> None:
    with _HISTORY_LOCK:
        history: list[dict[str, Any]] = []
        if HISTORY_PATH.exists():
            try:
                raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    history = raw
            except Exception:
                pass
        history.insert(0, _normalize_history_account(record))
        atomic_write_text(
            HISTORY_PATH,
            json.dumps(history[:100], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _normalize_history_account(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    uid = _int_or_none(out.get("user_id") or out.get("pixiv_user_id"))
    owner = _find_account_by_pixiv_uid(uid) if uid is not None else None
    if owner:
        owner_id = str(owner.get("id") or "").strip()
        row_id = str(out.get("account_id") or "").strip()
        if owner_id and owner_id != row_id:
            if row_id:
                out.setdefault("account_id_original", row_id)
            out["account_id"] = owner_id
            out["account_corrected"] = True
        if owner_id and (out.get("account_corrected") or not out.get("account_label")):
            out["account_label"] = account_display_name(owner_id)
        if not out.get("user_name") and owner.get("user_name"):
            out["user_name"] = owner.get("user_name")
        if not out.get("user_account") and owner.get("user_account"):
            out["user_account"] = owner.get("user_account")
    return out


def list_upload_history(limit: int = 20) -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        raw = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        items: list[dict[str, Any]] = []
        for item in raw[: max(1, min(limit, 100))]:
            if not isinstance(item, dict):
                continue
            row = _normalize_history_account(item)
            aid = str(row.get("account_id") or "").strip()
            if aid and not row.get("account_label"):
                row["account_label"] = account_display_name(aid)
            items.append(row)
        return items
    except Exception as exc:
        _logger.warning("上传历史 %s 读取失败，已按空历史处理: %s", HISTORY_PATH, exc)
    return []


def _upload_account_hint() -> str:
    account_id = get_active_account_id()
    if not account_id:
        return ""
    active = get_active_account() or {}
    label = account_display_name(account_id)
    who = active.get("user_name") or active.get("user_account") or ""
    return f"账号「{label}」" + (f"（{who}）" if who else "")


def upload_illust(
    *,
    image_id: str = "",
    image_ids: list[str] | None = None,
    group_id: str = "",
    title: str = "",
    caption: str = "",
    tags: list[str] | None = None,
    restrict: int | None = None,
    illust_type: int | None = None,
    skip_failed_pipeline: bool = False,
    account_id: str = "",
) -> dict[str, Any]:
    cfg = load_config()
    upload_cfg = cfg.get("upload") or {}
    payload = {
        "image_id": image_id,
        "image_ids": image_ids or [],
        "group_id": group_id,
    }
    ids, _ = _resolve_selection(payload)
    with _LOCK:
        if _JOB.get("status") == "running":
            _JOB["message"] = f"上传前校验/后处理 {len(ids)} 张（多图请耐心等待）…"
    pipeline_ran = _ensure_upload_ready(
        ids,
        cfg,
        progress_label="上传前强制打码/清元数据",
        skip_failed=skip_failed_pipeline,
    )
    if skip_failed_pipeline:
        ids = [x for x in ids if x in pipeline_ran]
        if not ids:
            raise RuntimeError("本次选择的图片后处理全部失败，已跳过上传")
    require_processed = _upload_require_processed(cfg)
    image_paths = _resolve_upload_paths(ids, cfg, require_processed=require_processed)
    primary_id = ids[0]

    saved_post = _load_post_draft(primary_id, ids)
    if not title:
        title = str(saved_post.get("title") or saved_post.get("title_zh") or "")
    if not caption:
        caption = str(saved_post.get("caption") or saved_post.get("caption_zh") or "")
    if tags is None or not tags:
        tags = list(saved_post.get("tags") or [])

    if not title or not caption or not tags:
        extra = f"共 {len(ids)} 页系列图" if len(ids) > 1 else ""
        draft = generate_post_copy(
            image_id=primary_id,
            extra=extra,
            save_draft=True,
            run_pipeline=False,
        )
        post = draft.get("post") or {}
        title = title or str(post.get("title") or "无题")
        caption = caption or str(post.get("caption") or "")
        if not tags:
            tags = list(post.get("tags") or [])

    tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    if not tags:
        tags = list(
            (cfg.get("account") or {}).get("default_tags")
            or DEFAULTS["account"]["default_tags"]
        )
    tags = _balance_upload_tags(tags, max_tags=PIXIV_MAX_TAGS)[:PIXIV_MAX_TAGS]

    resolved_illust_type = illust_type
    if resolved_illust_type is None and len(ids) > 1:
        resolved_illust_type = 1
    if resolved_illust_type is None:
        resolved_illust_type = int(upload_cfg.get("illust_type", 0))

    record = _upload_pixiv_illust(
        image_paths,
        title=title,
        caption=caption,
        tags=tags,
        restrict=int(restrict if restrict is not None else upload_cfg.get("restrict", 0)),
        illust_type=int(resolved_illust_type),
        ai_type=upload_cfg.get("ai_type", 1),
        account_id=account_id,
    )
    uploaded_files = [p.name for p in image_paths]
    msg = f"上传成功（后处理版 {uploaded_files[0]}）"
    if len(ids) > 1:
        msg = f"系列上传成功（{len(ids)} 页，均为 *_final.png）"
    return {
        "ok": True,
        **record,
        "image_id": primary_id,
        "image_ids": ids,
        "group_id": group_id or None,
        "pipeline_ran": pipeline_ran,
        "upload_variant": "processed",
        "uploaded_files": uploaded_files,
        "message": msg,
    }


def start_upload_job(payload: dict[str, Any]) -> dict[str, Any]:
    """后台浏览器投稿（仅上传，不跑人设/文案流水线）。"""
    try:
        batches = _resolve_selection_batches(payload)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "message": str(exc)}

    # 检查与置位必须在同一次锁内完成，否则两个并发请求都会通过检查。
    with _LOCK:
        if _JOB.get("status") == "running":
            return {"ok": False, "message": "已有任务进行中", "job": copy.deepcopy(_JOB)}
        _JOB.clear()
        upload_hint = _upload_account_hint()
        _JOB.update(
            {
                "status": "running",
                "step": "upload",
                "message": (
                    f"浏览器自动投稿中（{upload_hint}，Chrome 会短暂弹出）…"
                    if upload_hint
                    else "浏览器自动投稿中（Chrome 会短暂弹出）…"
                ),
                "progress": {"current": 0, "total": 0, "percent": 0, "label": "上传"},
                "result": None,
            }
        )
    _remember_job_request("upload", payload)

    def _worker() -> None:
        results: list[dict[str, Any]] = []
        try:
            title = str(payload.get("title") or "")
            caption = str(payload.get("caption") or "")
            tags = (
                list(payload["tags"])
                if isinstance(payload.get("tags"), list)
                else None
            )
            pipeline_failures: list[dict[str, str]] = []
            for i, batch in enumerate(batches):
                image_ids = list(batch.get("image_ids") or [])
                group_id = str(batch.get("group_id") or "")
                if len(batches) > 1:
                    _job_progress(
                        current=i,
                        total=len(batches),
                        label="浏览器投稿",
                        step="upload",
                        message=(
                            f"浏览器投稿系列 {i + 1}/{len(batches)}"
                            f"（{len(image_ids)} 张，Chrome 会短暂弹出）…"
                        ),
                    )
                result = upload_illust(
                    image_id=str(payload.get("image_id") or image_ids[0]),
                    image_ids=image_ids,
                    group_id=group_id,
                    title=title,
                    caption=caption,
                    tags=tags,
                    restrict=payload.get("restrict"),
                    illust_type=payload.get("illust_type"),
                    skip_failed_pipeline=len(image_ids) > 1 or len(batches) > 1,
                    account_id=str(payload.get("account_id") or ""),
                )
                with _LOCK:
                    pipeline_failures = list(_JOB.get("pipeline_failures") or [])
                results.append(result)
                _job_progress(
                    current=i + 1,
                    total=len(batches),
                    label="浏览器投稿",
                    step="upload",
                    message=f"浏览器投稿系列 {i + 1}/{len(batches)} 完成",
                )
            msg = (
                f"已上传 {len(results)} 个系列"
                if len(results) > 1
                else (results[0].get("message") if results else "上传成功")
            )
            with _LOCK:
                _JOB.update(
                    {
                        "status": "done",
                        "step": "done",
                        "message": msg or "上传成功",
                        "progress": {
                            "current": len(batches),
                            "total": len(batches),
                            "percent": 100,
                            "label": "完成",
                        },
                        "result": {
                            "steps": ["upload"],
                            "uploads": results,
                            "batch_count": len(results),
                            "pipeline_failures": pipeline_failures,
                        },
                    }
                )
        except Exception as exc:
            with _LOCK:
                _JOB.update(
                    {
                        "status": "error",
                        "step": "error",
                        "message": str(exc),
                        "progress": _JOB.get("progress") or {},
                        "result": {
                            "steps": ["upload"],
                            "uploads": results,
                            "error": str(exc),
                        },
                    }
                )

    threading.Thread(target=_worker, daemon=True).start()
    first = batches[0]
    first_ids = list(first.get("image_ids") or [])
    if first.get("merged"):
        gids = list(first.get("group_ids") or [])
        label = f"{len(gids)} 个系列合并 · 共 {len(first_ids)} 张"
    elif len(batches) > 1:
        total = sum(len(b.get("image_ids") or []) for b in batches)
        label = f"{len(batches)} 个系列 · 共 {total} 张"
    else:
        label = f"系列 {len(first_ids)} 张" if len(first_ids) > 1 else first_ids[0]
    group_ids = [str(b.get("group_id") or "") for b in batches if b.get("group_id")]
    upload_hint = _upload_account_hint()
    start_msg = f"浏览器投稿已启动（{label}）"
    if upload_hint:
        start_msg += f" · 使用 {upload_hint}"
    return {
        "ok": True,
        "message": start_msg,
        "image_id": first_ids[0] if first_ids else "",
        "image_ids": first_ids,
        "group_id": str(first.get("group_id") or "") or None,
        "group_ids": group_ids or None,
        "batch_count": len(batches),
        "selection": str(first.get("group_id") or first_ids[0] if first_ids else ""),
    }


def launch_one_click(payload: dict[str, Any]) -> dict[str, Any]:
    """一键起号：后处理 → AI 人设(可选) → AI 小作文 → 上传 Pixiv。"""
    try:
        batches = _resolve_selection_batches(payload)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "message": str(exc)}
    first_ids = list(batches[0].get("image_ids") or [])
    primary_id = first_ids[0] if first_ids else ""

    # 检查与置位必须在同一次锁内完成，否则两个并发请求都会通过检查。
    with _LOCK:
        if _JOB.get("status") == "running":
            return {"ok": False, "message": "已有起号任务进行中", "job": copy.deepcopy(_JOB)}
        _JOB.clear()
        _JOB.update(
            {
                "status": "running",
                "message": "启动中…",
                "step": "init",
                "progress": {"current": 0, "total": 0, "percent": 0, "label": "启动"},
                "result": None,
            }
        )
    _remember_job_request("launch", payload)

    def _worker() -> None:
        steps: list[str] = []
        uploads: list[dict[str, Any]] = []
        last_post: dict[str, Any] = {}
        try:

            cfg = load_config()
            account = cfg.get("account") or {}

            if payload.get("regen_persona") or not account.get("persona"):
                with _LOCK:
                    _JOB["step"] = "persona"
                    _JOB["message"] = "AI 导演：生成账号人设…"
                gen = generate_persona(
                    direction=str(payload.get("direction") or ""),
                    nickname_hint=str(payload.get("nickname_hint") or ""),
                    save=True,
                )
                steps.append("persona")
                persona = gen["persona"]
            else:
                persona = account.get("persona") or {}

            upload_cfg = cfg.get("upload") or {}
            total_images = sum(len(b.get("image_ids") or []) for b in batches)
            pipeline_failures: list[dict[str, str]] = []
            skipped_batches: list[dict[str, Any]] = []
            for i, batch in enumerate(batches):
                image_ids = list(batch.get("image_ids") or [])
                group_id = str(batch.get("group_id") or "")
                batch_primary = image_ids[0]
                batch_label = (
                    f"系列 {i + 1}/{len(batches)}"
                    if len(batches) > 1
                    else "当前系列"
                )

                if upload_cfg.get("auto_pipeline", True):
                    _job_progress(
                        current=0,
                        total=total_images or len(image_ids),
                        label="后处理",
                        step="pipeline",
                        message=(
                            f"后处理：{batch_label} {len(image_ids)} 张自动补跑…"
                            if len(image_ids) > 1
                            else f"后处理：{batch_label} 自动补跑超分/打码/元数据…"
                        ),
                    )
                    pipeline_ran = _ensure_upload_ready(
                        image_ids,
                        cfg,
                        progress_label=f"后处理：{batch_label}",
                        skip_failed=True,
                    )
                    with _LOCK:
                        pipeline_failures = list(_JOB.get("pipeline_failures") or [])
                    if pipeline_ran != image_ids:
                        image_ids = [x for x in image_ids if x in pipeline_ran]
                        if not image_ids:
                            skipped = {
                                "group_id": group_id,
                                "label": batch_label,
                                "reason": "all pipeline images failed",
                            }
                            skipped_batches.append(skipped)
                            with _LOCK:
                                _JOB["skipped_batches"] = list(skipped_batches)
                            _job_progress(
                                current=i + 1,
                                total=len(batches),
                                label="后处理",
                                step="pipeline",
                                message=f"后处理：{batch_label} 全部失败，已跳过该系列",
                            )
                            continue
                        batch_primary = image_ids[0]
                    if pipeline_ran and "pipeline" not in steps:
                        steps.append("pipeline")

                _job_progress(
                    current=i,
                    total=len(batches),
                    label="AI 文案",
                    step="copy",
                    message=f"AI 导演：{batch_label} 写投稿文案…",
                )
                extra_bits = [str(payload.get("extra") or "").strip()]
                if batch.get("merged"):
                    src_n = len(batch.get("group_ids") or [])
                    extra_bits.append(
                        f"用户将 {src_n} 个生成系列共 {len(image_ids)} 页"
                        "合并为一篇 Pixiv 多页漫画投稿，请写能概括整组的标题与简介。"
                    )
                elif len(image_ids) > 1:
                    extra_bits.append(
                        f"这是同一源作品的 {len(image_ids)} 页系列图，按漫画多页投稿。"
                    )
                elif len(batches) > 1:
                    extra_bits.append(
                        f"这是第 {i + 1}/{len(batches)} 个独立系列，请写适合该组图案的标题与简介。"
                    )
                copy = generate_post_copy(
                    image_id=batch_primary,
                    extra=" ".join(x for x in extra_bits if x),
                    persona=persona,
                    save_draft=True,
                    run_pipeline=False,
                )
                post = copy.get("post") or {}
                last_post = post
                if "copy" not in steps:
                    steps.append("copy")

                title = str(payload.get("title") or post.get("title") or "无题")
                caption = str(payload.get("caption") or post.get("caption") or "")
                tags = payload.get("tags")
                if tags is None:
                    tags = list(post.get("tags") or [])

                _job_progress(
                    current=i,
                    total=len(batches),
                    label="浏览器投稿",
                    step="upload",
                    message=(
                        f"浏览器投稿 {batch_label}（{len(image_ids)} 页，Chrome 会短暂弹出）…"
                        if len(image_ids) > 1
                        else f"浏览器投稿 {batch_label}（Chrome 会短暂弹出）…"
                    ),
                )
                result = upload_illust(
                    image_id=batch_primary,
                    image_ids=image_ids,
                    group_id=group_id,
                    title=title,
                    caption=caption,
                    tags=list(tags) if isinstance(tags, list) else None,
                    restrict=payload.get("restrict"),
                    illust_type=payload.get("illust_type"),
                    account_id=str(payload.get("account_id") or ""),
                )
                uploads.append(result)
                _job_progress(
                    current=i + 1,
                    total=len(batches),
                    label="浏览器投稿",
                    step="upload",
                    message=f"浏览器投稿 {batch_label} 完成",
                )
            if "upload" not in steps:
                steps.append("upload")

            done_msg = (
                f"起号流水线完成：已上传 {len(uploads)} 个系列"
                if len(uploads) > 1
                else "起号流水线完成"
            )
            with _LOCK:
                _JOB.update(
                    {
                        "status": "done",
                        "step": "done",
                        "message": done_msg,
                        "progress": {
                            "current": len(batches),
                            "total": len(batches),
                            "percent": 100,
                            "label": "完成",
                        },
                        "result": {
                            **(uploads[-1] if uploads else {}),
                            "steps": steps,
                            "post": last_post,
                            "persona": persona,
                            "uploads": uploads,
                            "batch_count": len(uploads),
                            "pipeline_failures": pipeline_failures,
                            "skipped_batches": skipped_batches,
                        },
                    }
                )
        except Exception as exc:
            with _LOCK:
                _JOB.update(
                    {
                        "status": "error",
                        "step": "error",
                        "message": str(exc),
                        "progress": _JOB.get("progress") or {},
                        "result": {
                            "steps": steps,
                            "uploads": uploads,
                            "error": str(exc),
                        },
                    }
                )

    threading.Thread(target=_worker, daemon=True).start()
    first_batch = batches[0]
    if first_batch.get("merged"):
        src = list(first_batch.get("group_ids") or [])
        label = f"{len(src)} 个系列合并 · 共 {len(first_ids)} 张"
    elif len(batches) > 1:
        total = sum(len(b.get("image_ids") or []) for b in batches)
        label = f"{len(batches)} 个系列 · 共 {total} 张"
    else:
        label = f"系列 {len(first_ids)} 张" if len(first_ids) > 1 else primary_id
    group_ids = list(first_batch.get("group_ids") or []) or [
        str(b.get("group_id") or "") for b in batches if b.get("group_id")
    ]
    return {
        "ok": True,
        "message": (
            f"起号流水线已启动（{label}） · 使用 {upload_hint}"
            if (upload_hint := _upload_account_hint())
            else f"起号流水线已启动（{label}）"
        ),
        "image_id": primary_id,
        "image_ids": first_ids,
        "group_id": str(batches[0].get("group_id") or "") or None,
        "group_ids": group_ids or None,
        "batch_count": len(batches),
        "selection": str(batches[0].get("group_id") or primary_id),
    }


def _candidate_item(
    item: dict[str, Any],
    pipe_overrides: dict[str, Any],
    *,
    artifact_index: dict[str, dict[str, list[Path]]] | None = None,
    pipeline_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stem = str(item.get("id") or "")
    final = resolve_png(f"{stem}_final.png", root=GENERATED_DIR)
    pipe_state = pipeline_item_state(
        stem,
        overrides=pipe_overrides,
        _artifact_index=artifact_index,
        _config=pipeline_config,
    )
    return {
        "id": stem,
        "image_url": item.get("image_url"),
        "processed_url": item.get("processed_url") or (
            f"/data/generated/{final.name}" if final.exists() else ""
        ),
        "work_id": item.get("work_id"),
        "created_at": item.get("created_at"),
        "model": item.get("model"),
        "pipeline": pipe_state,
    }


def list_launch_groups() -> list[dict[str, Any]]:
    """供起号页按系列（生成图库微缩图组）选择。"""
    cfg = load_config()
    pipe_overrides = _upload_pipeline_overrides(cfg)
    pipeline_config = merge_pipeline_config(pipe_overrides)
    artifact_index = build_artifact_index()
    grouped_items: dict[str, list[dict[str, Any]]] = {}
    for item in scan_all_items():
        group_id = group_key_for_item(item)
        grouped_items.setdefault(group_id, []).append(item)
    out: list[dict[str, Any]] = []
    for summary in list_groups():
        group_id = str(summary.get("group_id") or "")
        raw_items = grouped_items.get(group_id) or []
        if not raw_items:
            continue
        raw_items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        items = [
            _candidate_item(
                item,
                pipe_overrides,
                artifact_index=artifact_index,
                pipeline_config=pipeline_config,
            )
            for item in raw_items
        ]
        if not items:
            continue
        source_work_id = raw_items[0].get("work_id")
        missing = sum(1 for it in items if (it.get("pipeline") or {}).get("missing"))
        out.append(
            {
                "group_id": group_id,
                "work_id": source_work_id,
                "count": len(items),
                "cover_url": summary.get("cover_url") or items[0].get("image_url"),
                "latest_at": summary.get("latest_at") or "",
                "source_title": (
                    f"作品 {source_work_id}"
                    if source_work_id
                    else "独立生成"
                ),
                "image_ids": [it["id"] for it in items],
                "items": items,
                "pipeline_pending": missing,
            }
        )
    return out


def list_launch_candidates() -> list[dict[str, Any]]:
    """供起号页选择的试生成图列表。"""
    cfg = load_config()
    pipe_overrides = _upload_pipeline_overrides(cfg)
    pipeline_config = merge_pipeline_config(pipe_overrides)
    artifact_index = build_artifact_index()
    items = scan_all_items()
    out: list[dict[str, Any]] = []
    for item in items[:80]:
        out.append(
            _candidate_item(
                item,
                pipe_overrides,
                artifact_index=artifact_index,
                pipeline_config=pipeline_config,
            )
        )
    return out


def provider_presets() -> dict[str, Any]:
    return {"presets": AI_PROVIDER_PRESETS}

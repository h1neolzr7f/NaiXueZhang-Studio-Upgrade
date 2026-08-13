"""Butler execute implementation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import copy
import json
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nai_prompt_optimizer import ai_status
from pixiv_launch import chat_json
from product_ops import build_product_health
from gallery_catalog import get_db, get_spec
from gallery_guard import EMPTY_GALLERY_CRAWL_MSG, main_gallery_empty
from server_shared import (
    CONFIG,
    CRAWLER_WATCHDOG,
    DATA_DIR,
    DB,
    GALLERY_LOCAL_ONLY,
    GALLERY_SCOPE,
    ROOT,
)
from studio_service import build_studio_draft, import_from_work, list_queue_for_studio, studio_config
from nai_anima_adapter import apply_anima_character_to_comment
from knowledge_catalog import get_knowledge_catalog
from reference_catalog import get_reference_catalog
from work_refs import WorkRef
from butler_gallery_operations import (
    CONFIRM_OPERATIONS as GALLERY_CONFIRM_OPERATIONS,
    READ_OPERATIONS as GALLERY_READ_OPERATIONS,
    catalogue as gallery_operation_catalogue,
    confirmation_summary as gallery_confirmation_summary,
    execute_confirmed as execute_gallery_confirmed,
    execute_read as execute_gallery_read,
    handles as handles_gallery_operation,
    normalize as normalize_gallery_operation,
    resolve_work_selection,
)
from butler.service_api import api


async def _execute_confirmed(action: dict[str, Any]) -> dict[str, Any]:
    tool = action["tool"]
    args = action["arguments"]
    if tool == "rebuild_knowledge_catalog":
        return api._execute_auto(action)
    if tool == "start_crawler":
        if api._main_gallery_empty():
            raise ValueError(api.EMPTY_GALLERY_CRAWL_MSG)
        from crawler_control import start_pixiv_crawler

        result = start_pixiv_crawler(watch=True)
        return {
            "ok": True,
            "tool": tool,
            "message": "Pixiv 采集已启动（watch 模式）",
            **result,
        }
    if tool == "stop_crawler":
        from crawler_control import stop_crawler_processes

        stopped = stop_crawler_processes()
        return {
            "ok": True,
            "tool": tool,
            "message": "Pixiv 采集进程已停止",
            "stopped": stopped.get("pixiv") or [],
        }
    if tool == "configure_crawler":
        if api._main_gallery_empty():
            raise ValueError(api.EMPTY_GALLERY_CRAWL_MSG)
        from pixiv_nai_crawler import load_task, save_task

        if args.get("proxy_url") not in (None, ""):
            raise ValueError(api.SETTINGS_ENDPOINT_HINT)
        allowed = {
            "enabled", "source_mode", "search_queries", "user_ids", "rankings",
            "request_delay_sec", "browser_mode",
        }
        patch = {key: value for key, value in args.items() if key in allowed}
        if not patch:
            raise ValueError("没有可更新的采集配置项")
        updated = save_task({**load_task(root=api.ROOT), **patch}, root=api.ROOT)
        return {
            "ok": True,
            "tool": tool,
            "message": "采集配置已更新并保存",
            "task": {
                "enabled": bool(updated.get("enabled")),
                "source_mode": updated.get("source_mode") or "auto",
                "search_queries": list(updated.get("search_queries") or []),
                "request_delay_sec": updated.get("request_delay_sec") or 0,
                "proxy_url": updated.get("proxy_url") or "",
                "browser_mode": bool(updated.get("browser_mode")),
            },
        }
    if tool == "retry_exhausted_previews":
        from pixiv_nai_crawler import retry_quarantined

        result = retry_quarantined(root=api.ROOT)
        return {
            "ok": True,
            "tool": tool,
            "message": "已重试隔离区作品",
            **result,
        }
    if tool == "modify_setting":
        from pixiv_nai_crawler import load_task, save_task

        hint = str(args.pop("_forbidden_setting_hint", "") or "")
        if any(args.get(key) not in (None, "") for key in ("ai_api_base", "api_base", "proxy_url", "port")):
            raise ValueError(api.SETTINGS_ENDPOINT_HINT)

        task_keys = {
            "enabled", "source_mode", "search_queries", "user_ids",
            "rankings", "request_delay_sec", "browser_mode",
            "watch_interval_sec",
        }
        ai_keys = {"ai_model": "model"}
        changes: list[str] = []
        task_patch: dict[str, object] = {}
        for key, value in args.items():
            if key in task_keys:
                task_patch[key] = value
                changes.append(key)
        ai_patch: dict[str, object] = {}
        for key, target in ai_keys.items():
            if key in args and args[key] not in (None, ""):
                ai_patch[target] = str(args[key])
                changes.append(key)

        if not changes:
            raise ValueError(hint or ("没有可修改的白名单配置项。" + api.SETTINGS_ENDPOINT_HINT))
        if api._crawler_mutation_blocked_when_empty(task_patch):
            raise ValueError(api.EMPTY_GALLERY_CRAWL_MSG)

        messages: list[str] = []
        if task_patch:
            updated = save_task(
                {**load_task(root=api.ROOT), **task_patch}, root=api.ROOT
            )
            messages.append("采集任务配置已保存")
        if ai_patch:
            import json as _json

            from atomic_io import atomic_write_text as _atomic_write_text

            ai_path = api.DATA_DIR / "ai.local.json"
            current: dict[str, object] = {}
            if ai_path.exists():
                try:
                    current = _json.loads(
                        ai_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    current = {}
            current.update(ai_patch)
            ai_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(
                ai_path,
                _json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            messages.append("AI 模型配置已保存（密钥与接口地址未改动）")
        if hint:
            messages.append(hint)
        return {
            "ok": True,
            "tool": tool,
            "message": "；".join(messages),
            "changed": changes,
        }
    if tool == "set_auto_mode":
        auto_mode = bool(args.get("auto_mode"))
        auto_repair = bool(args.get("auto_repair", False))
        api._save_auto_config(auto_mode=auto_mode, auto_repair=auto_repair)
        return {
            "ok": True,
            "tool": tool,
            "auto_mode": auto_mode,
            "auto_repair": auto_repair,
            "message": (
                "自动模式已更新：生产工单（生成/投稿准备/采集）仍需确认；"
                + ("具名检修剧本可自动执行。" if auto_repair else "检修剧本仍需确认。")
            ),
        }
    if tool == "auto_repair":
        performed: list[str] = []
        remaining: list[str] = []

        # 1) 用户级代理环境变量：只诊断，不修改系统设置
        import subprocess as _sp

        for var in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"):
            try:
                check = _sp.run(
                    ["powershell", "-NoProfile", "-Command",
                     "[Environment]::GetEnvironmentVariable('" + var + "','User')"],
                    capture_output=True, text=True, timeout=20,
                )
            except Exception:
                check = None
            value = (check.stdout or "").strip() if check else ""
            if value:
                remaining.append(
                    var + " 当前为 " + value
                    + "。检修剧本不会修改系统代理，请在 Windows 环境变量里自行确认。"
                )

        # 2) 采集进程：只报告，不拉起（启动采集属于生产工单）
        from crawler_control import list_pixiv_crawler_pids
        from pixiv_nai_crawler import load_task, retry_quarantined

        task = load_task(root=api.ROOT)
        if task.get("enabled") and not list_pixiv_crawler_pids():
            if api._main_gallery_empty():
                remaining.append(api.EMPTY_GALLERY_CRAWL_MSG)
            else:
                remaining.append(
                    "采集任务已启用但进程未运行。检修不会自动拉起爬虫，请确认生产工单后再启动。"
                )

        # 3) 隔离区重试
        quarantined = retry_quarantined(root=api.ROOT)
        retried = int(quarantined.get("retried") or 0)
        if retried > 0:
            performed.append("已重试隔离区作品 " + str(retried) + " 条")

        # 4) AI 配置检查
        ai_path = api.DATA_DIR / "ai.local.json"
        if not ai_path.exists():
            remaining.append("AI 密钥未配置：请到 设置页 → AI 服务 填写（小镜不触碰密钥）")

        # 5) 采集参数健康（间隔过小提示）。空库时不改采集配置。
        delay = float(task.get("request_delay_sec") or 0)
        if task.get("enabled") and delay < 1.0:
            if api._main_gallery_empty():
                remaining.append(api.EMPTY_GALLERY_CRAWL_MSG)
            else:
                from pixiv_nai_crawler import save_task

                save_task({**task, "request_delay_sec": max(delay, 1.0)}, root=api.ROOT)
                performed.append("请求间隔过小（" + str(delay) + "s），已调整为至少 1s")

        if not performed and not remaining:
            performed.append("未发现需要自动修复的问题")
        return {
            "ok": True,
            "tool": tool,
            "performed": performed,
            "remaining": remaining,
            "message": (
                "自动修复完成：" + "；".join(performed)
                if performed else "无需修复"
            ) + (("；需人工：" + "；".join(remaining)) if remaining else ""),
        }
    if tool == "add_to_queue":
        from production_queue import add

        gallery_id = api._gallery_id(args.get("gallery_id"))
        for work_id in args["work_ids"]:
            api._require_work(int(work_id), gallery_id)
        items = [
            add(int(work_id), note=args.get("note") or "", gallery_id=gallery_id)
            for work_id in args["work_ids"]
        ]
        return {"ok": True, "tool": tool, "items": items, "message": "已加入待生成"}
    if tool == "remove_from_queue":
        from production_queue import remove

        gallery_id = api._gallery_id(args.get("gallery_id"))
        items = [
            remove(int(work_id)) if gallery_id == "site" else remove(int(work_id), gallery_id)
            for work_id in args["work_ids"]
        ]
        return {"ok": True, "tool": tool, "items": items, "message": "已移出待生成"}
    if tool == "clear_queue":
        from production_queue import clear

        return {"tool": tool, "message": "待生成队列已清空", **clear()}
    if tool == "batch_generate":
        return api._start_batch_workflow(args, prepare_pixiv=False)
    if tool == "batch_generate_and_prepare_pixiv":
        return api._start_batch_workflow(args, prepare_pixiv=True)
    if tool == "batch_director":
        from nai_director import preview_director_batch, start_director_batch

        sources = list(args.get("sources") or [])
        recipe = dict(args.get("recipe") or {})
        preview = preview_director_batch(sources, recipe)
        if not preview.get("ready") or not preview.get("preview_id"):
            raise RuntimeError("批量导演零费用预检未通过")
        result = start_director_batch(
            sources,
            recipe,
            confirmed=True,
            preview_id=str(preview["preview_id"]),
        )
        if not result.get("ok"):
            raise RuntimeError(str(result.get("message") or "批量导演启动失败"))
        return {
            **result,
            "tool": tool,
            "message": "批量导演已开始；可在独立导演页查看实时进度与交付报告",
            "director_url": "/director",
        }
    if tool == "prepare_pixiv_submission":
        workflow_id = api._begin_workflow(tool, "正在启动投稿准备…")
        api._spawn_workflow(api._prepare_pixiv_workflow(args))
        return {
            "ok": True,
            "tool": tool,
            "workflow_id": workflow_id,
            "message": "投稿准备已启动；完成后会停在上传前等待你检查",
        }
    if tool == "generate_image":
        from nai_batch import start_studio_generate
        from nai_char import clean_plain_ark_workbench_draft
        from char_swap_config import load_config as load_char_swap_config

        work_id = int(args.get("work_id") or 0)
        gallery_id = api._gallery_id(args.get("gallery_id"))
        if work_id:
            api._require_work(work_id, gallery_id)
        comment = clean_plain_ark_workbench_draft(
            copy.deepcopy(api._build_generation_comment(args)),
            work_id or None,
            int(args.get("page_index") or 0),
            gallery_id=gallery_id,
        )
        copies = int(args.get("batch_count") or 1)
        manual_config = load_char_swap_config()
        result = start_studio_generate(
            comment if isinstance(comment, dict) else {},
            work_id=work_id or None,
            page_index=int(args.get("page_index") or 0),
            copies=copies,
            source_gallery_id=gallery_id,
            seed_policy="",
            force_free=bool(manual_config.get("force_free", True)),
            prompt_profile=str(manual_config.get("prompt_profile") or "native"),
        )
        if not result.get("ok"):
            raise RuntimeError(str(result.get("message") or "生图任务未能入队"))
        return {
            "ok": True,
            "tool": tool,
            "task_id": result.get("task_id"),
            "queued": result.get("queued"),
            "batch": result.get("batch"),
            "retry_policy": "no-5xx-retry",
            "message": result.get("message") or "已入队生成任务；5xx 不会自动重试",
        }
    if tool in api.GALLERY_CONFIRM_OPERATIONS:
        return await asyncio.to_thread(api.execute_gallery_confirmed, tool, args)
    raise ValueError(f"工具不能确认执行：{tool}")



async def confirm_action(confirmation_id: str, *, approve: bool) -> dict[str, Any]:
    token = api._clean_text(confirmation_id, limit=200)
    with api._PENDING_LOCK:
        api._prune_pending()
        pending = api._PENDING.pop(token, None)
    if not pending:
        raise ValueError("确认已失效或不存在，请重新下达指令")
    action = pending["action"]
    if not approve:
        api._write_audit(action["tool"], "cancelled", action["arguments"])
        return {"ok": True, "cancelled": True, "tool": action["tool"], "message": "已取消，不会执行"}
    try:
        result = await api._execute_confirmed(action)
    except Exception as exc:
        api._write_audit(action["tool"], "failed", action["arguments"], detail=str(exc))
        raise
    api._write_audit(action["tool"], "executed", action["arguments"])
    return {"ok": True, "cancelled": False, "result": result}


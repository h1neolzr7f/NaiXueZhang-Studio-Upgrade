"""Butler chat implementation."""

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
from butler.tool_loop_bridge import KERNEL_READ_TOOLS, execute_chat_action


def run_chat(
    message: str,
    history: Any = None,
    image: Any = None,
    preplanned: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = api.ai_status()
    if not status.get("has_api_key") or not status.get("model"):
        raise RuntimeError("请先在设置或发布台配置 AI API Key 和模型")
    plan = copy.deepcopy(preplanned) if isinstance(preplanned, dict) else api.request_plan(message, history, image)
    reply = api._clean_text(plan.get("reply"), limit=2000) or "我已经分析了这条指令。"
    raw_actions = plan.get("actions") or []
    if not isinstance(raw_actions, list):
        raise ValueError("AI 计划中的 actions 不是数组")

    results: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    auto_repair = api._auto_repair_enabled()
    for raw in raw_actions[:api.MAX_ACTIONS]:
        try:
            action = api.normalize_action(raw)
            tool = action["tool"]
            from butler.agents import reject_foreign_tool

            foreign = reject_foreign_tool(tool)
            if foreign:
                rejected.append({"tool": tool, "reason": foreign})
                continue
            if tool in {"start_crawler", "configure_crawler"} and api._main_gallery_empty():
                rejected.append({"tool": tool, "reason": api.EMPTY_GALLERY_CRAWL_MSG})
                continue
            if tool in KERNEL_READ_TOOLS:
                from butler.agents import current_agent

                handled = execute_chat_action(action, agent_id=current_agent() or "shared")
                if handled and handled.get("status") == "succeeded":
                    data = handled.get("data") if isinstance(handled.get("data"), dict) else {}
                    results.append({"ok": True, "tool": tool, "kernel": True, **data})
                elif handled and handled.get("status") == "workflow_requested":
                    pending.append(api._stage_confirmation(action))
                else:
                    rejected.append(
                        {
                            "tool": tool,
                            "reason": str((handled or {}).get("error") or handled or "kernel preview failed"),
                        }
                    )
                continue
            if tool in api._AUTO_TOOLS:
                results.append(api._execute_auto(action))
            elif tool in api._REPAIR_TOOLS and auto_repair:
                import asyncio as _asyncio
                import concurrent.futures as _futures

                with _futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_asyncio.run, api._execute_confirmed(action))
                    results.append(future.result(timeout=300))
            elif tool in api._CONFIRM_TOOLS or tool in api._REPAIR_TOOLS:
                pending.append(api._stage_confirmation(action))
        except Exception as exc:
            rejected.append(
                {
                    "tool": api._clean_text(raw.get("tool") if isinstance(raw, dict) else "", limit=80),
                    "reason": api._clean_text(exc, limit=300),
                }
            )
    from butler.companion_state import consume_handoff, planner_memory_context
    from butler.agents import current_agent

    extras: list[str] = []
    handoff = consume_handoff(current_agent())
    if handoff:
        extras.append(
            f"交接自{handoff.get('from_agent') or '另一位助手'}："
            f"{handoff.get('note') or '请接着刚才的上下文。'}"
        )
    remembered = planner_memory_context(5)
    if remembered:
        extras.append("已确认偏好：" + "；".join(remembered))
    if extras:
        reply = f"{reply}\n" + "\n".join(extras)
    return {
        "ok": True,
        "reply": reply,
        "model": status.get("model") or "",
        "tool_results": results,
        "pending_actions": pending,
        "rejected_actions": rejected,
        "companion": {"handoff": handoff, "memories": remembered},
    }



def butler_status() -> dict[str, Any]:
    ai = api.ai_status()
    try:
        from nai_api import token_status

        token = token_status()
    except Exception:
        token = {"has_token": False}
    with api._PENDING_LOCK:
        api._prune_pending()
        pending_count = len(api._PENDING)
    try:
        from nai_batch import batch_status

        batch_raw = batch_status()
        batch = {
            "status": batch_raw.get("status") or "idle",
            "message": batch_raw.get("message") or "",
            "total": int(batch_raw.get("total") or 0),
            "done": int(batch_raw.get("done") or 0),
            "ok": int(batch_raw.get("ok_count") or 0),
            "failed": int(batch_raw.get("fail_count") or 0),
        }
    except Exception:
        batch = {"status": "idle", "total": 0, "done": 0, "ok": 0, "failed": 0}
    try:
        from nai_director import director_batch_status

        director_raw = director_batch_status()
        director = {
            "status": director_raw.get("status") or "idle",
            "message": director_raw.get("message") or "",
            "total": int(director_raw.get("total") or 0),
            "done": int(director_raw.get("done") or 0),
            "ok": int(director_raw.get("ok_count") or 0),
            "failed": int(director_raw.get("fail_count") or 0),
            "task_id": director_raw.get("task_id") or "",
        }
    except Exception:
        director = {"status": "idle", "total": 0, "done": 0, "ok": 0, "failed": 0, "task_id": ""}
    try:
        from post_pipeline import pipeline_status

        pipeline_raw = pipeline_status()
        pipeline = {
            "status": pipeline_raw.get("status") or "idle",
            "message": pipeline_raw.get("message") or "",
            "total": int(pipeline_raw.get("total") or 0),
            "done": int(pipeline_raw.get("done") or 0),
        }
    except Exception:
        pipeline = {"status": "idle", "total": 0, "done": 0}
    from butler.agents import public_agents

    return {
        "ok": True,
        "ai": {
            "configured": bool(ai.get("has_api_key") and ai.get("model")),
            "provider": ai.get("provider") or "",
            "model": ai.get("model") or "",
            "api_base": ai.get("api_base") or "",
        },
        "generation": {"configured": bool(token.get("has_token"))},
        "skills": api.SKILL_CATALOG,
        "tools": api.TOOL_CATALOG,
        "workflow": api.workflow_status(),
        "batch": batch,
        "director": director,
        "pipeline": pipeline,
        "pending_count": pending_count,
        "audit": api.recent_audit(),
        "agents": public_agents(),
        "safety": {
            "confirmation_ttl_seconds": api.CONFIRM_TTL_SECONDS,
            "direct_publish_enabled": False,
            "direct_delete_enabled": False,
            "confirmed_delete_enabled": True,
            "secrets_exposed_to_browser": False,
        },
    }


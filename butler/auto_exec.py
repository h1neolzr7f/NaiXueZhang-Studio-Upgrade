"""Butler auto exec implementation."""

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


def _execute_auto(action: dict[str, Any]) -> dict[str, Any]:
    tool = action["tool"]
    args = action["arguments"]
    from butler.agents import reject_foreign_tool

    foreign = reject_foreign_tool(tool)
    if foreign:
        raise ValueError(foreign)
    if tool in {"compile_nai_preview", "gallery_index_preview"}:
        from butler.agents import current_agent
        from butler.tool_loop_bridge import execute_chat_action

        handled = execute_chat_action(action, agent_id=current_agent() or "shared")
        if handled and handled.get("status") == "succeeded":
            data = handled.get("data") if isinstance(handled.get("data"), dict) else {}
            return {"ok": True, "tool": tool, "kernel": True, **data}
        raise ValueError(str((handled or {}).get("error") or handled or "kernel preview failed"))
    if tool == "search_gallery":
        gallery_id = api._gallery_id(args.get("gallery_id"))
        # ``DB`` remains the canonical site-gallery singleton; only the new
        # galleries need catalog resolution.
        db = api.DB if gallery_id == "site" else api.get_db(gallery_id)
        data = db.search_works(
            q=args["q"],
            prompt=args["prompt"],
            page=1,
            page_size=int(args["limit"]),
            sort=args["sort"],
            time_range=args["time_range"],
            local_scope=api.GALLERY_SCOPE if gallery_id == "site" and api.GALLERY_LOCAL_ONLY else "",
            skip_total=True,
            nai_only=True,
        )
        return {
            "ok": True,
            "tool": tool,
            "query": {key: args[key] for key in ("q", "prompt", "sort", "time_range")},
            "gallery_id": gallery_id,
            "items": [api._work_card(item, gallery_id) for item in (data.get("items") or [])],
        }
    if tool == "search_character_references":
        result = api.get_reference_catalog().search(
            query=str(args.get("q") or ""),
            gender=str(args.get("gender") or ""),
            copyright_name=str(args.get("copyright") or ""),
            source=str(args.get("source") or ""),
            limit=int(args.get("limit") or 8),
        )
        return {
            "ok": True,
            "tool": tool,
            "query": {
                key: args.get(key) for key in ("q", "gender", "copyright", "source")
            },
            "items": list(result.get("items") or []),
            "total": int(result.get("total") or 0),
            "references_url": "/references",
            "provider": "local",
            "generation_calls": 0,
            "message": f"本地角色资料库找到 {int(result.get('total') or 0)} 条结果",
        }
    if tool == "search_style_references":
        result = api.get_reference_catalog().search_styles(
            query=str(args.get("q") or ""),
            kind=str(args.get("kind") or ""),
            source=str(args.get("source") or ""),
            limit=int(args.get("limit") or 8),
        )
        return {
            "ok": True,
            "tool": tool,
            "query": {key: args.get(key) for key in ("q", "kind", "source")},
            "items": list(result.get("items") or []),
            "total": int(result.get("total") or 0),
            "references_url": "/references?tab=styles",
            "provider": "local",
            "generation_calls": 0,
            "message": f"本地画风资料库找到 {int(result.get('total') or 0)} 条结果",
        }
    if tool == "inspect_reference_catalog":
        stats = api.get_reference_catalog().stats()
        return {
            "ok": True,
            "tool": tool,
            "total": int(stats.get("total") or 0),
            "sources": list(stats.get("sources") or []),
            "genders": dict(stats.get("genders") or {}),
            "copyrights": list(stats.get("copyrights") or []),
            "recent_imports": list(stats.get("recent_imports") or []),
            "trait_facets": list(stats.get("trait_facets") or []),
            "style_references": list(stats.get("style_references") or []),
            "schema_version": int(stats.get("schema_version") or 0),
            "compiler_version": int(stats.get("compiler_version") or 0),
            "references_url": "/references",
            "provider": "local",
            "generation_calls": 0,
            "message": (
                f"本地 NAI 角色资料库共有 {int(stats.get('total') or 0)} 个角色，"
                f"来自 {len(stats.get('sources') or [])} 个来源"
            ),
        }
    if tool == "rebuild_knowledge_catalog":
        receipt = api.get_knowledge_catalog(ensure_ready=False).refresh_builtin_sources()
        return {
            **receipt,
            "ok": True,
            "tool": tool,
            "provider": "local",
            "model_calls": 0,
            "settings_url": "/settings#knowledgeCatalog",
            "message": (
                f"本地知识库已增量更新：{int(receipt.get('documents') or 0)} 个来源、"
                f"{int(receipt.get('chunks') or 0)} 个知识块"
            ),
        }
    if tool == "audit_gallery":
        from gallery_audit_service import run_gallery_audit

        return run_gallery_audit(args)
    if tool == "compare_gallery_candidates":
        from gallery_audit_service import run_gallery_comparison

        return run_gallery_comparison(args)
    if tool == "inspect_work":
        gallery_id = api._gallery_id(args.get("gallery_id"))
        db = api.get_db(gallery_id)
        work_id = int(args["work_id"])
        detail = api._require_work(work_id, gallery_id)
        work = detail.get("work") or {}
        card = api._work_card(work, gallery_id)
        images = detail.get("images") or []
        if images and not card["thumb"]:
            first = images[0]
            card["thumb"] = api._thumb_url({"thumb_path": first.get("local_path")}, gallery_id)
        snippet = db.get_work_prompt_snippet(work_id, int(args["page_index"]))
        return {
            "ok": True,
            "tool": tool,
            "work": card,
            "prompt": api._clean_text(snippet.get("snippet"), limit=1200),
            "page_index": int(snippet.get("page_index") or 0),
        }
    if tool == "list_queue":
        result = api.list_queue_for_studio(int(args["limit"]))
        return {"ok": True, "tool": tool, **result}
    if tool == "prepare_studio":
        return api._prepare_studio(args)
    if tool == "prepare_character_reference":
        return api._prepare_character_reference(args)
    if tool == "prepare_remix":
        api._require_work(int(args["work_id"]), args.get("gallery_id") or "site")
        recipe = args.get("remix_recipe") or {}
        if (
            api._gallery_id(args.get("gallery_id")) != "site"
            and (recipe.get("transform") or {}).get("enabled")
        ):
            raise ValueError("法典/QQ 图库可换画风并复用 Prompt 生成；角色槽换角目前仅支持网站图库")
        from butler.remix import prepare_remix_draft

        return prepare_remix_draft(args)
    if tool == "inspect_production":
        from generated_gallery import list_groups
        from nai_batch import batch_status
        from pixiv_launch import launch_status
        from post_pipeline import pipeline_status

        limit = int(args.get("limit") or 5)
        groups = [
            {
                key: item.get(key)
                for key in ("group_id", "work_id", "count", "cover_thumb", "latest_at")
            }
            for item in list_groups()[:limit]
        ]
        pipeline = pipeline_status()
        generation = batch_status()
        pixiv = launch_status()
        return {
            "ok": True,
            "tool": tool,
            "generated_groups": groups,
            "generation": {
                key: generation.get(key)
                for key in ("task_id", "status", "message", "total", "done", "ok_count", "fail_count")
            },
            "pipeline": {
                key: pipeline.get(key)
                for key in ("status", "message", "total", "done", "ok", "fail")
            },
            "submission": {
                key: pixiv.get(key)
                for key in ("status", "message", "step", "progress")
            },
        }
    if tool == "read_logs":
        from pathlib import Path

        logs_root = Path(api.CONFIG.get("root") or api.ROOT) / "logs"
        name = str(args.get("name") or "all").casefold()
        lines = max(50, min(int(args.get("lines") or 200), 500))
        sources = {
            "server": ["server.log", "server.codex.log"],
            "crawler": ["pixiv-nai-crawler.err.log", "pixiv-nai-crawler.out.log"],
            "watchdog": ["crawler-watchdog.log"],
            "heartbeat": ["pixiv-nai-intake-heartbeat.json"],
        }
        wanted = (
            {name: sources[name]} if name in sources
            else sources if name == "all"
            else {}
        )
        tail: dict[str, str] = {}
        for key, filenames in wanted.items():
            for filename in filenames:
                path = logs_root / filename
                if not path.exists():
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                tail[f"{key}:{filename}"] = "\n".join(
                    content.splitlines()[-lines:]
                )
        if not tail:
            return {
                "ok": True,
                "tool": tool,
                "logs": {},
                "message": f"logs 目录（{logs_root}）中未找到匹配的日志文件",
            }
        return {"ok": True, "tool": tool, "logs": tail}

    if tool == "diagnose_error":
        from pathlib import Path

        from pixiv_nai_crawler import get_report

        logs_root = Path(api.CONFIG.get("root") or api.ROOT) / "logs"
        since_lines = max(50, min(int(args.get("since_lines") or 200), 500))
        error_text = str(args.get("error_text") or "")
        collected: list[str] = []
        for filename in (
            "server.log", "server.codex.log",
            "pixiv-nai-crawler.err.log", "crawler-watchdog.log",
        ):
            path = logs_root / filename
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    collected.append(
                        f"--- {filename} ---\n"
                        + "\n".join(content.splitlines()[-since_lines:])
                    )
                except OSError:
                    pass
        report = get_report(root=api.ROOT)
        findings: list[str] = []
        haystack = error_text + "\n" + "\n".join(collected)
        haystack_l = haystack.casefold()
        hints = (
            ("网络连接失败/代理", "http", "proxy", "connect", "10061", "timeout",
             "原因：本机代理环境变量（ALL_PROXY 等）可能指向已关闭的 Clash/代理端口。"
             "修复：删除系统环境变量 ALL_PROXY/HTTP_PROXY/HTTPS_PROXY 后重试，或重新打开代理软件。"),
            ("端口被占用", "port", "address already in use", "10048",
             "原因：目标端口已被其他进程占用。"
             "修复：任务管理器结束占用进程，或更改配置端口后重启服务。"),
            ("playwright 缺失", "playwright", "browser", "executable",
             "原因：浏览器渲染通道缺少 Chromium 或 playwright 未安装。"
             "修复：运行 pip install playwright 后执行 playwright install chromium。"),
            ("API Key 缺失", "api key", "unauthorized", "401", "invalid key",
             "原因：AI 或 NAI 服务的密钥未配置或已失效。"
             "修复：到设置页重新填写密钥（密钥只保存在本机配置页，小镜不读取密钥值）。"),
            ("采集无结果", "no works", "empty", "0 works",
             "原因：当前搜索词/榜单没有命中作品，或任务未启用。"
             "修复：检查采集配置（搜索词、榜单、enabled），确认网络可达 www.pixiv.net。"),
        )
        for label, *keys, advice in hints:
            if any(key in haystack_l for key in keys):
                findings.append(f"[{label}] {advice}")
        if not findings:
            findings.append(
                "未匹配到常见故障模式。建议：1) 把完整报错原文发给小镜；"
                "2) 查看采集页的报告与隔离区；3) 重启服务后重试。"
            )
        return {
            "ok": True,
            "tool": tool,
            "findings": findings,
            "crawler_status": report.get("status") or "unknown",
            "crawler_source_mode": report.get("source_mode") or "",
            "logs_tail": collected[-1] if collected else "",
        }

    if tool == "product_guide":
        from software_help import product_guide as _product_guide

        payload = _product_guide(args.get("topic") or "全部")
        return {"ok": True, "tool": tool, **payload}

    if tool == "inspect_config":
        import json as _json
        from pathlib import Path

        from pixiv_nai_crawler import load_task

        task = load_task(root=api.ROOT)
        ai_cfg = api.DATA_DIR / "ai.local.json"
        cfg_path = Path(api.ROOT) / "config.json"
        port = None
        if cfg_path.exists():
            try:
                port = _json.loads(
                    cfg_path.read_text(encoding="utf-8")
                ).get("port")
            except (OSError, ValueError):
                port = None
        task_obj = dict(task)
        return {
            "ok": True,
            "tool": tool,
            "config": {
                "root": str(api.ROOT),
                "port": port,
                "ai_configured": ai_cfg.exists(),
                "intake_enabled": bool(task_obj.get("enabled")),
                "intake_source_mode": task_obj.get("source_mode") or "auto",
                "intake_delay_sec": task_obj.get("request_delay_sec") or 0,
                "intake_proxy": task_obj.get("proxy_url") or "",
                "intake_browser_mode": bool(task_obj.get("browser_mode")),
                "intake_search_queries": len(task_obj.get("search_queries") or []),
                "intake_rankings": len(task_obj.get("rankings") or []),
            },
            "message": "配置概览（密钥值不展示）",
        }

    if tool == "inspect_crawler":
        from crawler_control import list_pixiv_crawler_pids
        from pixiv_nai_crawler import get_report, load_task

        pids = list_pixiv_crawler_pids()
        report = get_report(root=api.ROOT)
        task = load_task(root=api.ROOT)
        return {
            "ok": True,
            "tool": tool,
            "running": bool(pids),
            "pids": pids,
            "task": {
                "enabled": bool(task.get("enabled")),
                "source_mode": task.get("source_mode") or "auto",
                "search_queries": list(task.get("search_queries") or []),
                "user_ids": list(task.get("user_ids") or []),
                "rankings": list(task.get("rankings") or []),
                "request_delay_sec": task.get("request_delay_sec") or 0,
                "proxy_url": task.get("proxy_url") or "",
                "browser_mode": bool(task.get("browser_mode")),
            },
            "report": {
                key: report.get(key)
                for key in ("status", "source_mode", "started_at", "finished_at",
                            "works_recovered", "pages_fetched", "accepted_pages",
                            "rejected_pages", "failed_pages", "last_error")
            },
            "message": (
                "采集进程运行中" if pids else
                ("采集进程未运行（任务已配置，可随时启动）" if task.get("enabled")
                 else "采集任务未启用")
            ),
        }
    if tool == "inspect_operations":
        health = api.build_product_health(api.CONFIG, api.ROOT)
        crawler = api.CRAWLER_WATCHDOG.status()
        return {
            "ok": bool(health.get("ok")),
            "tool": tool,
            "health": {
                "ok": bool(health.get("ok")),
                "checks": dict(health.get("checks") or {}),
                "warnings": list(health.get("warnings") or []),
                "data": dict(health.get("data") or {}),
            },
            "crawler": {
                key: crawler.get(key)
                for key in (
                    "enabled",
                    "work_remaining",
                    "crawler_running",
                    "supervisor_running",
                    "work",
                    "last_action",
                    "last_check",
                    "message",
                )
            },
            "ops_url": "/ops",
        }
    if tool in api.GALLERY_READ_OPERATIONS:
        return api.execute_gallery_read(tool, args)
    raise ValueError(f"工具不能自动执行：{tool}")


"""Deep Module for safe gallery operations exposed to the Butler Workflow.

The Interface is intentionally small: catalogue, normalize, execute_read and
execute_confirmed.  Routes and the Butler reuse the same domain implementations;
the language model never receives a generic HTTP or filesystem tool.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gallery_catalog import get_db
from work_refs import WorkRef


@dataclass(frozen=True)
class OperationSpec:
    name: str
    label: str
    risk: str
    category: str
    description: str


_SPECS = (
    OperationSpec("inspect_capabilities", "查看可用操作", "read", "operations", "列出助手可完成及必须人工处理的图库操作。"),
    OperationSpec("list_favorites", "查看收藏", "read", "collection", "查看跨图库收藏作品。"),
    OperationSpec("add_to_favorites", "加入收藏", "confirm", "collection", "把一个或多个图库作品加入收藏。"),
    OperationSpec("remove_from_favorites", "取消收藏", "confirm", "collection", "把一个或多个图库作品移出收藏。"),
    OperationSpec("list_generated", "查看生成成果", "read", "generated", "查看生成系列，或读取指定系列的成果。"),
    OperationSpec("delete_generated_item", "删除生成成果", "confirm", "generated", "删除一张指定的本地生成成果。"),
    OperationSpec("delete_generated_group", "删除生成系列", "confirm", "generated", "删除指定生成系列及其本地成果。"),
    OperationSpec("run_pipeline", "执行后处理", "confirm", "pipeline", "按全局配置补跑指定成果或所有缺失后处理。"),
    OperationSpec("review_generated", "审核生成成果", "confirm", "pipeline", "把指定成果人工标记为通过或剔除。"),
    OperationSpec("inspect_crawler", "查看采集状态", "read", "crawler", "查看三图库采集进程、任务与耗尽封面状态。"),
    OperationSpec("start_crawler", "启动采集", "confirm", "crawler", "启动网站、QQ、Codex 或全部采集任务。"),
    OperationSpec("stop_crawler", "停止采集", "confirm", "crawler", "停止网站、QQ、Codex 或全部采集任务。"),
    OperationSpec("configure_crawler", "配置采集任务", "confirm", "crawler", "保存网站采集范围、排序、阶段并可选择重启。"),
    OperationSpec("retry_exhausted_previews", "重试耗尽封面", "confirm", "crawler", "把有界数量的耗尽封面重新入队并可选择启动采集。"),
    OperationSpec("cancel_generation", "取消生成任务", "confirm", "generation", "请求取消当前或指定的批量生成任务。"),
)

_BY_NAME = {item.name: item for item in _SPECS}
READ_OPERATIONS = frozenset(item.name for item in _SPECS if item.risk == "read")
CONFIRM_OPERATIONS = frozenset(item.name for item in _SPECS if item.risk == "confirm")

PROTECTED_OPERATIONS = (
    {"name": "publish_pixiv", "label": "真实 Pixiv 上传", "reason": "必须在投稿页人工核对并发布"},
    {"name": "manage_secrets", "label": "账号、Token 与密钥", "reason": "只能在专用配置页修改"},
    {"name": "arbitrary_io", "label": "任意文件或网络请求", "reason": "不向语言模型开放通用执行入口"},
)


def catalogue() -> list[dict[str, str]]:
    return [asdict(item) for item in _SPECS]


def handles(name: str) -> bool:
    return name in _BY_NAME


def _text(value: Any, *, name: str, limit: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{name} 是必填项")
    if len(text) > limit:
        raise ValueError(f"{name} 不能超过 {limit} 个字符")
    return text


def _integer(
    value: Any,
    *,
    name: str,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int | None:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} 必须在 {minimum}..{maximum} 之间")
    return parsed


def _gallery(value: Any = None) -> str:
    return WorkRef.parse(1, str(value or "site")).gallery_id


def _work_ids(value: Any) -> list[int]:
    raw = value if isinstance(value, list) else [value]
    result: list[int] = []
    for item in raw[:20]:
        parsed = _integer(item, name="work_id", minimum=1, maximum=2**63 - 1)
        if parsed is not None and parsed not in result:
            result.append(parsed)
    if not result:
        raise ValueError("需要至少一个有效作品 ID")
    return result


def resolve_work_selection(args: dict[str, Any], *, maximum: int = 20) -> tuple[str, list[int]]:
    """Resolve explicit IDs or a bounded local query into stable work identities."""
    gallery_id = _gallery(args.get("gallery_id"))
    if args.get("work_ids") is not None or args.get("work_id") is not None:
        return gallery_id, _work_ids(args.get("work_ids", args.get("work_id")))[:maximum]
    q = _text(args.get("q"), name="q", limit=300)
    prompt = _text(args.get("prompt"), name="prompt", limit=1000)
    if not (q or prompt):
        raise ValueError("需要作品 ID，或提供 q/prompt 本地查询条件")
    sort = _text(args.get("sort") or "new", name="sort", limit=20).lower()
    time_range = _text(args.get("time_range") or "all", name="time_range", limit=20).lower()
    if sort not in {"new", "monthly", "count"}:
        raise ValueError("sort 不受支持")
    if time_range not in {"all", "day", "week", "month", "year"}:
        raise ValueError("time_range 不受支持")
    limit = int(_integer(args.get("limit"), name="limit", minimum=1, maximum=maximum, default=min(6, maximum)) or 1)
    local_scope = ""
    if gallery_id == "site":
        from server_shared import GALLERY_LOCAL_ONLY, GALLERY_SCOPE

        local_scope = GALLERY_SCOPE if GALLERY_LOCAL_ONLY else ""
    data = get_db(gallery_id).search_works(
        q=q,
        prompt=prompt,
        page=1,
        page_size=limit,
        sort=sort,
        time_range=time_range,
        local_scope=local_scope,
        skip_total=True,
        nai_only=True,
    )
    ids = [int(item.get("id") or 0) for item in (data.get("items") or []) if int(item.get("id") or 0) > 0]
    if not ids:
        raise ValueError("本地查询没有找到可操作的作品")
    return gallery_id, ids[:maximum]


def _safe_asset_id(value: Any, *, name: str) -> str:
    text = _text(value, name=name, limit=180, required=True)
    if any(char in text for char in ("/", "\\", "\x00")) or text in {".", ".."}:
        raise ValueError(f"{name} 格式无效")
    return text


def normalize(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Normalize one registered operation or raise for malformed arguments."""
    if name not in _BY_NAME:
        raise KeyError(name)
    if name in {"inspect_capabilities", "inspect_crawler"}:
        return {}
    if name in {"list_favorites", "list_generated"}:
        normalized: dict[str, Any] = {
            "limit": _integer(args.get("limit"), name="limit", minimum=1, maximum=40, default=12)
        }
        if name == "list_generated" and args.get("group_id"):
            normalized["group_id"] = _safe_asset_id(args.get("group_id"), name="group_id")
        return normalized
    if name in {"add_to_favorites", "remove_from_favorites"}:
        gallery_id, work_ids = resolve_work_selection(args)
        return {
            "gallery_id": gallery_id,
            "work_ids": work_ids,
        }
    if name == "delete_generated_item":
        return {"image_id": _safe_asset_id(args.get("image_id"), name="image_id")}
    if name == "delete_generated_group":
        return {"group_id": _safe_asset_id(args.get("group_id"), name="group_id")}
    if name == "run_pipeline":
        image_ids: list[str] = []
        raw_ids = args.get("image_ids", args.get("image_id"))
        if raw_ids not in (None, ""):
            raw = raw_ids if isinstance(raw_ids, list) else [raw_ids]
            for item in raw[:200]:
                image_id = _safe_asset_id(item, name="image_id")
                if image_id not in image_ids:
                    image_ids.append(image_id)
        group_id = _safe_asset_id(args.get("group_id"), name="group_id") if args.get("group_id") else ""
        all_missing = bool(args.get("all_missing", not image_ids and not group_id))
        if not (image_ids or group_id or all_missing):
            raise ValueError("后处理需要 image_ids、group_id 或 all_missing=true")
        return {
            "image_ids": image_ids,
            "group_id": group_id,
            "all_missing": all_missing,
            "only_missing": bool(args.get("only_missing", True)),
        }
    if name == "review_generated":
        action = _text(args.get("action"), name="action", limit=20, required=True).lower()
        aliases = {"approve": "approve", "approved": "approve", "pass": "approve", "通过": "approve",
                   "exclude": "exclude", "excluded": "exclude", "reject": "exclude", "剔除": "exclude", "排除": "exclude"}
        if action not in aliases:
            raise ValueError("action 只能是 approve（通过）或 exclude（剔除）")
        return {
            "image_id": _safe_asset_id(args.get("image_id"), name="image_id"),
            "action": aliases[action],
            "note": _text(args.get("note"), name="note", limit=300),
        }
    if name in {"start_crawler", "stop_crawler"}:
        target = _text(args.get("target") or "site", name="target", limit=20).lower()
        aliases = {"website": "site", "aitag": "site", "qq": "qqgroup", "qun": "qqgroup", "director": "codex"}
        target = aliases.get(target, target)
        if target not in {"site", "qqgroup", "codex", "all"}:
            raise ValueError("target 只能是 site、qqgroup、codex 或 all")
        normalized = {"target": target}
        if name == "start_crawler":
            phase = _text(args.get("phase"), name="phase", limit=20).lower()
            if phase and phase not in {"all", "search", "detail", "preview"}:
                raise ValueError("phase 只能是 all、search、detail 或 preview")
            normalized.update({"phase": phase, "watch": bool(args.get("watch", True))})
        return normalized
    if name == "configure_crawler":
        from crawler_task import get_task

        current = get_task()
        phase = _text(args.get("crawler_phase") or current.get("crawler_phase") or "all", name="crawler_phase", limit=20).lower()
        sort = _text(args.get("search_sort") or current.get("search_sort") or "new", name="search_sort", limit=20).lower()
        time_range = _text(args.get("search_time_range") or current.get("search_time_range") or "all", name="search_time_range", limit=20).lower()
        if phase not in {"all", "search", "detail", "preview"}:
            raise ValueError("crawler_phase 无效")
        if sort not in {"new", "monthly"}:
            raise ValueError("search_sort 无效")
        if time_range not in {"all", "day", "week", "month", "year", "current"}:
            raise ValueError("search_time_range 无效")
        query = _text(args.get("search_query", current.get("search_query")), name="search_query", limit=500)
        if not query and phase in {"all", "search"}:
            raise ValueError("搜索类采集任务需要 search_query")
        return {
            "search_query": query,
            "search_sort": sort,
            "search_time_range": time_range,
            "search_max_pages": _integer(args.get("search_max_pages"), name="search_max_pages", minimum=0, maximum=100000, default=int(current.get("search_max_pages") or 0)),
            "search_batch_pages": _integer(args.get("search_batch_pages"), name="search_batch_pages", minimum=1, maximum=100, default=int(current.get("search_batch_pages") or 8)),
            "crawler_phase": phase,
            "dataset_name": _text(args.get("dataset_name") or current.get("dataset_name") or "local", name="dataset_name", limit=100),
            "reset_search": bool(args["reset_search"]) if "reset_search" in args else None,
            "restart": bool(args.get("restart", False)),
        }
    if name == "retry_exhausted_previews":
        return {
            "limit": _integer(args.get("limit"), name="limit", minimum=1, maximum=5000, default=1000),
            "restart": bool(args.get("restart", False)),
        }
    if name == "cancel_generation":
        return {"task_id": _text(args.get("task_id"), name="task_id", limit=80)}
    return {}


def _work_summary(gallery_id: str, work_id: int) -> dict[str, Any]:
    detail = get_db(gallery_id).get_work_detail(work_id) or {}
    work = detail.get("work") or {}
    return {
        "gallery_id": gallery_id,
        "work_id": work_id,
        "title": str(work.get("title") or work.get("caption") or f"作品 {work_id}")[:180],
        "image_count": int(work.get("image_count") or len(detail.get("images") or [])),
        "url": f"/i/{work_id}?gallery={gallery_id}",
    }


def _ensure_work(gallery_id: str, work_id: int) -> None:
    if not get_db(gallery_id).get_work_detail(work_id):
        raise ValueError(f"{gallery_id} 图库中的作品 {work_id} 不存在")


def execute_read(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a normalized read operation."""
    if name == "inspect_capabilities":
        from butler.agents import agent_record, agent_tools

        allowed = agent_tools()
        record = agent_record() or {}
        specs = [spec for spec in _SPECS if not allowed or spec.name in allowed]
        by_category: dict[str, list[str]] = {}
        for spec in specs:
            by_category.setdefault(spec.category, []).append(spec.label)
        other = str(record.get("handoff") or "")
        agent_name = str(record.get("name") or "助手")
        return {
            "ok": True,
            "tool": name,
            "agent": str(record.get("id") or ""),
            "supported": len(allowed) if allowed is not None else len(_SPECS),
            "categories": by_category,
            "tools": sorted(allowed) if allowed is not None else [spec.name for spec in _SPECS],
            "protected": list(PROTECTED_OPERATIONS),
            "message": (
                f"{agent_name}只负责{record.get('duty') or '当前工作台'}，白名单 {len(allowed or specs)} 项；"
                f"越权操作请切换到另一位助手。"
                if record
                else f"助手已接入 {len(_SPECS)} 项图库操作；敏感操作仍需专用页面人工完成。"
            ),
            "handoff": other,
        }
    if name == "list_favorites":
        from favorites import list_refs

        refs = list_refs()[: int(args.get("limit") or 12)]
        items = [_work_summary(str(ref["gallery_id"]), int(ref["work_id"])) for ref in refs]
        return {"ok": True, "tool": name, "items": items, "count": len(items), "message": f"当前显示 {len(items)} 个收藏作品"}
    if name == "list_generated":
        from generated_gallery import get_group, list_groups

        group_id = str(args.get("group_id") or "")
        if group_id:
            group = get_group(group_id)
            if not group:
                raise ValueError(f"生成系列 {group_id} 不存在")
            return {"ok": True, "tool": name, "group": group, "items": list(group.get("items") or []), "message": f"生成系列 {group_id} 共 {len(group.get('items') or [])} 张"}
        groups = list_groups()[: int(args.get("limit") or 12)]
        compact = [
            {key: item.get(key) for key in ("group_id", "work_id", "source_gallery_id", "count", "cover_url", "cover_thumb", "latest_at")}
            for item in groups
        ]
        return {"ok": True, "tool": name, "groups": compact, "count": len(compact), "generated_url": "/generated", "message": f"当前显示 {len(compact)} 个生成系列"}
    if name == "inspect_crawler":
        from crawler_control import multi_crawler_status
        from crawler_task import get_task
        from progress import get_progress_snapshot

        progress = get_progress_snapshot()
        return {
            "ok": True,
            "tool": name,
            "crawlers": multi_crawler_status(),
            "task": get_task(),
            "progress": {
                key: progress.get(key)
                for key in ("status", "status_text", "overall_percent", "preview_exhausted", "crawler_work_remaining")
            },
            "progress_url": "/progress",
            "message": str(progress.get("status_text") or "采集状态已读取"),
        }
    raise ValueError(f"图库操作不能自动执行：{name}")


def confirmation_summary(name: str, args: dict[str, Any]) -> str:
    """Return a friendly, deterministic summary for the confirmation Interface."""
    if name == "add_to_favorites":
        return f"把 {len(args['work_ids'])} 个作品加入收藏"
    if name == "remove_from_favorites":
        return f"把 {len(args['work_ids'])} 个作品取消收藏"
    if name == "delete_generated_item":
        return f"永久删除本地生成成果 {args['image_id']}"
    if name == "delete_generated_group":
        return f"永久删除本地生成系列 {args['group_id']} 及其成果"
    if name == "run_pipeline":
        if args.get("all_missing"):
            return "按全局配置补跑所有缺失的后处理"
        if args.get("group_id"):
            return f"按全局配置处理生成系列 {args['group_id']}"
        return f"按全局配置处理 {len(args.get('image_ids') or [])} 张生成成果"
    if name == "review_generated":
        action = "通过并生成 final 文件" if args.get("action") == "approve" else "剔除并跳过后续上传"
        return f"把生成成果 {args['image_id']} 标记为{action}"
    if name == "start_crawler":
        phase = f"，阶段 {args.get('phase')}" if args.get("phase") else ""
        return f"启动 {args['target']} 采集{phase}"
    if name == "stop_crawler":
        return f"停止 {args['target']} 采集进程"
    if name == "configure_crawler":
        tail = "并立即重启" if args.get("restart") else "，下次启动时生效"
        return f"把网站采集配置为“{args.get('search_query') or '无新搜索'}” · {args.get('crawler_phase')}{tail}"
    if name == "retry_exhausted_previews":
        tail = "并启动采集" if args.get("restart") else ""
        return f"最多把 {args.get('limit', 1000)} 个耗尽封面重新入队{tail}"
    if name == "cancel_generation":
        return f"请求取消生成任务 {args.get('task_id') or '当前活动任务'}"
    return _BY_NAME[name].label


def execute_confirmed(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Execute a normalized operation after the Butler confirmation seam."""
    if name in {"add_to_favorites", "remove_from_favorites"}:
        from favorites import add, remove

        gallery_id = str(args["gallery_id"])
        fn = add if name == "add_to_favorites" else remove
        if name == "add_to_favorites":
            for work_id in args["work_ids"]:
                _ensure_work(gallery_id, int(work_id))
        items = [fn(work_id, gallery_id) for work_id in args["work_ids"]]
        verb = "加入收藏" if name == "add_to_favorites" else "取消收藏"
        return {"ok": True, "tool": name, "items": items, "message": f"已为 {len(items)} 个作品{verb}"}
    if name == "delete_generated_item":
        from generated_gallery import delete_item

        return {"tool": name, **delete_item(str(args["image_id"]))}
    if name == "delete_generated_group":
        from generated_gallery import delete_group

        return {"tool": name, **delete_group(str(args["group_id"]))}
    if name == "run_pipeline":
        from post_pipeline import start_pipeline

        payload = {key: value for key, value in args.items() if value not in ("", [], False)}
        result = start_pipeline(payload)
        if not result.get("ok"):
            raise ValueError(str(result.get("message") or "后处理启动失败"))
        return {"tool": name, "pipeline_url": "/pipeline", **result}
    if name == "review_generated":
        from post_pipeline import manual_review_image

        return {"tool": name, **manual_review_image(str(args["image_id"]), str(args["action"]), note=str(args.get("note") or ""))}
    if name == "start_crawler":
        from crawler_control import multi_crawler_status, start_crawler_target

        started = start_crawler_target(str(args["target"]), phase=str(args.get("phase") or "") or None, watch=bool(args.get("watch", True)))
        return {"ok": True, "tool": name, "started": started, "status": multi_crawler_status(), "progress_url": "/progress", "message": "采集任务已启动"}
    if name == "stop_crawler":
        from crawler_control import multi_crawler_status, stop_crawler_target

        stopped = stop_crawler_target(str(args["target"]))
        return {"ok": True, "tool": name, "stopped": stopped, "status": multi_crawler_status(), "message": "采集任务已停止"}
    if name == "configure_crawler":
        from crawler_task import apply_task

        payload = {key: value for key, value in args.items() if key not in {"reset_search", "restart"}}
        return {"tool": name, **apply_task(payload, reset_search=args.get("reset_search"), restart=bool(args.get("restart")))}
    if name == "retry_exhausted_previews":
        from crawler_control import restart_crawler
        from crawler_watchdog import requeue_exhausted_previews

        result = requeue_exhausted_previews(limit=int(args.get("limit") or 1000))
        if bool(args.get("restart")) and int(result.get("requeued") or 0) > 0:
            result["restart"] = restart_crawler()
        return {"tool": name, **result}
    if name == "cancel_generation":
        from nai_batch import cancel_batch

        return {"tool": name, **cancel_batch(str(args.get("task_id") or "") or None)}
    raise ValueError(f"图库操作不能确认执行：{name}")

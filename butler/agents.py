"""Two local assistants that share one AI API and split the tool surface.

客服小祥 handles maintenance and teaching. 助手凑企鹅 handles generation.
The frontend loads only one Live2D model at a time; the planner sees only that
persona's tools so prompts stay short and the model cannot invent the other
desk's actions. Execute paths re-check the same allowlist.
"""

from __future__ import annotations

import contextvars
import json
from pathlib import Path
from typing import Any


DEFAULT_AGENT = "sakiko"
_CURRENT_AGENT: contextvars.ContextVar[str] = contextvars.ContextVar("butler_agent", default="")

SAKIKO_TOOLS = frozenset(
    {
        "search_gallery",
        "audit_gallery",
        "compare_gallery_candidates",
        "inspect_work",
        "inspect_capabilities",
        "inspect_operations",
        "inspect_production",
        "inspect_config",
        "inspect_crawler",
        "start_crawler",
        "stop_crawler",
        "configure_crawler",
        "retry_exhausted_previews",
        "list_favorites",
        "add_to_favorites",
        "remove_from_favorites",
        "list_queue",
        "list_generated",
        "delete_generated_item",
        "delete_generated_group",
        "run_pipeline",
        "review_generated",
        "read_logs",
        "diagnose_error",
        "product_guide",
        "modify_setting",
        "set_auto_mode",
        "auto_repair",
        "rebuild_knowledge_catalog",
        "gallery_index_preview",
    }
)

TOMORI_TOOLS = frozenset(
    {
        "search_gallery",
        "inspect_work",
        "inspect_capabilities",
        "inspect_production",
        "inspect_reference_catalog",
        "search_character_references",
        "search_style_references",
        "prepare_character_reference",
        "prepare_studio",
        "prepare_remix",
        "generate_image",
        "batch_generate",
        "batch_generate_and_prepare_pixiv",
        "batch_director",
        "cancel_generation",
        "prepare_pixiv_submission",
        "list_queue",
        "add_to_queue",
        "remove_from_queue",
        "clear_queue",
        "list_generated",
        "compare_gallery_candidates",
        "compile_nai_preview",
        "gallery_index_preview",
    }
)

AGENTS: dict[str, dict[str, Any]] = {
    "sakiko": {
        "id": "sakiko",
        "name": "客服小祥",
        "short": "小祥",
        "duty": "处理、维护和使用教学",
        "desk": "ops",
        "handoff": "tomori",
        "live2d": "/assets/vendor/live2d-models/sakiko/causal/model.json",
        "tools": SAKIKO_TOOLS,
        "identity": (
            "你是客服小祥，气质参考丰川祥子：克制、负责、略锋利，不卖萌。"
            "只负责处理和维护：图库体检、采集、收藏、后处理、设置、排障、知识库，以及教小白怎么用本软件。"
            "出图、换角、导演、待生成队列改动和投稿准备属于助手凑企鹅；那些工具不在你的白名单里，不得规划、不得声称已经执行。"
            "教用法时只依据本地知识库和本机状态，先给入口和步骤，再说是否耗 Token、要不要确认。"
            "口吻可点到：「有事就说。」「做不来的事就别随口答应。」「这件事交给我。」"
        ),
    },
    "tomori": {
        "id": "tomori",
        "name": "助手凑企鹅",
        "short": "凑企鹅",
        "duty": "选材与生成",
        "desk": "studio",
        "handoff": "sakiko",
        "live2d": "/assets/vendor/live2d-models/tomori/casual/model.json",
        "tools": TOMORI_TOOLS,
        "identity": (
            "你是助手凑企鹅，互联网上高松灯的二创人设：轻声、认真、偶尔迷路，喜欢企鹅。"
            "可以轻轻用「咕」点缀，不要刷「咕咕嘎嘎」，也不要扮演成别的角色。"
            "只负责选材与生成：找素材、换角、出图、导演、待生成队列和投稿准备。"
            "采集、检修、改设置、删成果、后处理排障和教软件用法属于客服小祥；那些工具不在你的白名单里，不得规划。"
            "花钱、写入、投稿前必须先问用户。口吻可点到：「那个……我先帮你看看。」「因为想把图画好。」参数不够就追问，不要猜。"
        ),
    },
}

_ALIASES = {
    "xiang": "sakiko",
    "xiaoxiang": "sakiko",
    "sakiko": "sakiko",
    "maintenance": "sakiko",
    "ops": "sakiko",
    "小祥": "sakiko",
    "客服小祥": "sakiko",
    "祥子": "sakiko",
    "丰川祥子": "sakiko",
    "豐川祥子": "sakiko",
    "oblivionis": "sakiko",
    "tomori": "tomori",
    "generation": "tomori",
    "studio": "tomori",
    "灯": "tomori",
    "高松灯": "tomori",
    "高松燈": "tomori",
    "凑企鹅": "tomori",
    "湊企鹅": "tomori",
    "助手凑企鹅": "tomori",
    "企鹅": "tomori",
    "企鵝": "tomori",
}


def normalize_agent(value: Any) -> str:
    key = str(value or "").strip()
    if not key:
        return _CURRENT_AGENT.get() or ""
    mapped = _ALIASES.get(key) or _ALIASES.get(key.casefold()) or key.casefold()
    return mapped if mapped in AGENTS else ""


def set_current_agent(value: Any) -> contextvars.Token[str]:
    if value in (None, ""):
        return _CURRENT_AGENT.set("")
    return _CURRENT_AGENT.set(normalize_agent(value))


def reset_current_agent(token: contextvars.Token[str]) -> None:
    _CURRENT_AGENT.reset(token)


def current_agent() -> str:
    return _CURRENT_AGENT.get() or ""


def agent_record(value: Any = None) -> dict[str, Any] | None:
    key = normalize_agent(value) if value is not None else current_agent()
    return AGENTS.get(key)


def agent_tools(value: Any = None) -> frozenset[str] | None:
    record = agent_record(value)
    if not record:
        return None
    return frozenset(record["tools"])


def skill_visible_to(skill: dict[str, Any], agent_id: str = "") -> bool:
    desk = str(skill.get("desk") or "shared").strip() or "shared"
    if desk == "shared":
        return True
    key = normalize_agent(agent_id) if agent_id else current_agent()
    return bool(key) and desk == key


def companion_catalog() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "web" / "vendor" / "live2d-models" / "companions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def public_agents() -> list[dict[str, Any]]:
    catalog = companion_catalog()
    agents = []
    for item in AGENTS.values():
        companion = catalog.get(item["id"]) if isinstance(catalog.get(item["id"]), dict) else {}
        costumes = companion.get("costumes") if isinstance(companion.get("costumes"), dict) else {}
        other = AGENTS.get(str(item.get("handoff") or ""), {})
        agents.append(
            {
                "id": item["id"],
                "name": item["name"],
                "short": item["short"],
                "duty": item["duty"],
                "desk": item["desk"],
                "handoff": item["handoff"],
                "handoff_name": other.get("name") or "",
                "live2d": item["live2d"],
                "tool_count": len(item["tools"]),
                "default_costume": str(companion.get("default_costume") or ""),
                "costumes": [
                    {
                        "id": str(row.get("id") or key),
                        "label": str(row.get("label") or key),
                        "path": str(row.get("path") or ""),
                    }
                    for key, row in costumes.items()
                    if isinstance(row, dict)
                ],
                "situations": companion.get("situations") or {},
            }
        )
    return agents


def reject_foreign_tool(tool: str) -> str | None:
    allowed = agent_tools()
    name = str(tool or "").strip()
    if not allowed or name in allowed:
        return None
    record = agent_record() or {}
    other = AGENTS.get(str(record.get("handoff") or ""), {})
    return (
        f"当前是{record.get('name') or '助手'}的工作台，这项属于"
        f"{other.get('name') or '另一位助手'}的职责，请切换后再试。"
    )


def filter_plan_for_agent(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {"reply": "", "actions": []}
    payload = dict(plan)
    raw = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    kept: list[Any] = []
    dropped: list[str] = []
    for item in raw:
        tool = str(item.get("tool") or "") if isinstance(item, dict) else ""
        reason = reject_foreign_tool(tool)
        if reason:
            dropped.append(tool or "unknown")
        else:
            kept.append(item)
    payload["actions"] = kept
    if dropped:
        other = AGENTS.get(str((agent_record() or {}).get("handoff") or ""), {})
        hint = f"有些动作已交给{other.get('name') or '另一位助手'}，切换过去才能继续。"
        reply = str(payload.get("reply") or "").strip()
        payload["reply"] = f"{reply}\n{hint}".strip() if reply else hint
    return payload

"""LangGraph Implementation behind the intelligent-butler workflow Interface."""

from __future__ import annotations

import asyncio
import atexit
import os
import re
import secrets
from typing import Any

import butler_service as legacy
from knowledge_catalog import KnowledgeRefreshCancelled, get_knowledge_catalog
from paths import data_dir
from usage_ledger import usage_scope, usage_summary

from .workflow_helpers import (
    AutoExecutor,
    ButlerState,
    ConfirmedExecutor,
    Planner,
    UnknownExternalOutcome,
    WorkflowCancelled,
    _secure_local_configuration_plan,
)
from .workflow_runtime import ButlerWorkflowRuntime

_STATE_PATH = data_dir() / "butler_state.db"
_RUNTIME = ButlerWorkflowRuntime(_STATE_PATH)
atexit.register(_RUNTIME.store.close)


async def start_butler_runtime() -> None:
    await _RUNTIME.start()


async def close_butler_runtime() -> None:
    await _RUNTIME.close()


async def submit_butler_chat(
    message: str,
    history: Any = None,
    image: Any = None,
    intent: str = "",
    comparison: Any = None,
    agent: str = "",
) -> dict[str, Any]:
    from butler.agents import reset_current_agent, set_current_agent

    token = set_current_agent(agent)
    try:
        return await _submit_butler_chat(message, history, image, intent, comparison)
    finally:
        reset_current_agent(token)


async def _submit_butler_chat(
    message: str,
    history: Any = None,
    image: Any = None,
    intent: str = "",
    comparison: Any = None,
) -> dict[str, Any]:
    preplanned = None
    clean_intent = str(intent or "").strip().lower()
    if not clean_intent:
        from software_help import answer_software_question, looks_like_help_question, looks_like_question

        if looks_like_question(message):
            answer_id = f"answer-{secrets.token_hex(8)}"
            if image in (None, "", {}) and looks_like_help_question(message):
                help_answer = answer_software_question(message)
                sources = [
                    str(source).strip()
                    for source in list(help_answer.get("sources") or [])[:3]
                    if str(source).strip()
                ]
                source_line = f"\n依据：{'、'.join(sources)}" if sources else ""
                reply = f"{help_answer['answer']}{source_line}\n入口：{help_answer['page']}"
                from butler.agents import agent_record

                record = agent_record() or {}
                if record.get("id") == "tomori":
                    other = "客服小祥"
                    reply = (
                        f"用法这摊是{other}的工作台。我先把说明转给你：\n"
                        f"{reply}\n完整教学请切到{other}。"
                    )
                model = "local"
            else:
                with usage_scope(answer_id):
                    answer = await asyncio.to_thread(legacy.request_answer, message, history, image)
                reply = str(answer.get("reply") or "").strip() or "我暂时没能整理出可靠回答，请换一种问法。"
                model = str(legacy.ai_status().get("model") or "")
            return await _RUNTIME.record_answer(
                message,
                reply,
                answer_id=answer_id,
                image=image,
                model=model,
            )
    if clean_intent == "gallery_compare":
        action = legacy.normalize_action(
            {
                "tool": "compare_gallery_candidates",
                "arguments": {
                    "question": str(message or ""),
                    "candidates": comparison,
                },
            }
        )
        preplanned = {
            "reply": (
                "候选已经替你固定好了。我会只发送这 2–4 张低清图做一次比较，"
                "不会调用 NAI；完成后把选择理由和不足写进任务报告。"
            ),
            "actions": [action],
        }
    elif clean_intent == "gallery_audit":
        explicit_vision = any(
            token in str(message or "")
            for token in ("识图", "看图", "视觉", "画面评价", "评价图片", "分析图片")
        )
        preplanned = {
            "reply": (
                "我会用上游视觉模型检查最近图库的图片和状态；若上游拒绝，会直接告诉你。"
                if explicit_vision
                else "我会只读检查最近图库的本地状态，不调用识图，不会删除或重做任何内容。"
            ),
            "actions": [
                {
                    "tool": "audit_gallery",
                    "arguments": {
                        "sort": "new",
                        "time_range": "month",
                        "limit": 6,
                        "use_vision": explicit_vision,
                    },
                }
            ],
        }
    elif image in (None, "", {}) and not clean_intent:
        preplanned = _local_read_only_plan(message)
    engine = str(os.environ.get("BUTLER_ENGINE", "langgraph") or "langgraph").lower()
    if engine == "legacy":
        return await asyncio.to_thread(legacy.run_chat, message, history, image, preplanned)
    return await _RUNTIME.submit(
        message,
        history,
        image=image,
        preplanned=preplanned,
        run_in_background=True,
    )


def _knowledge_rebuild_plan() -> dict[str, Any]:
    return {
        "reply": (
            "好呀，我会逐份检查程序内置的可信说明，只增量更新有变化的内容。"
            "全程本地执行、不调用模型；进度和完成报告会放进任务中心。"
        ),
        "actions": [{"tool": "rebuild_knowledge_catalog", "arguments": {}}],
    }


async def submit_knowledge_rebuild() -> dict[str, Any]:
    """Submit the settings-page rebuild through the canonical Butler Workflow Interface."""

    return await _RUNTIME.submit(
        "增量更新本地软件知识库",
        preplanned=_knowledge_rebuild_plan(),
        run_in_background=True,
    )


def _local_read_only_plan(message: Any) -> dict[str, Any] | None:
    """Route a few unambiguous local reads without paying model latency or tokens."""
    source = " ".join(str(message or "").strip().lower().split())
    text = source.replace(" ", "")
    if not text or len(text) > 160:
        return None
    contextual = ("这个", "那个", "它", "刚才", "上一个", "第一个", "最后一个")
    # Natural multi-character commands are deterministic when they contain an
    # exact work id and explicit local preset names.  Build the same
    # replace_multi recipe used by the manual slot tool, then stop at the
    # normal generation confirmation gate (no model, vision, or NAI here).
    if any(token in text for token in ("换成", "替换成", "改成")) and "生成" in text and not any(
        token in text for token in ("不要生成", "不生成", "无需生成", "别生成")
    ):
        work_match = re.search(r"(?<!\d)(\d{6,})(?!\d)", text)
        names_match = re.search(
            r"(?:换成|替换成|改成)(.{2,120}?)(?:的?oc)?(?:后)?(?:批量)?生成",
            text,
        )
        if work_match and names_match:
            raw_names = re.split(r"和|与|、|及|,|，", names_match.group(1))
            names = [
                re.sub(r"(?:的)?oc$", "", name, flags=re.I).strip("的：:,，。")
                for name in raw_names
            ]
            names = [name for name in names if name]
            if 2 <= len(names) <= 6:
                copies_match = re.search(r"(?:生成|出)(\d{1,2})张", text)
                copies = int(copies_match.group(1)) if copies_match else 1
                if 1 <= copies <= 20:
                    replacements = [{"name": name} for name in names]
                    return {
                        "reply": (
                            f"收到，我会把作品 {work_match.group(1)} 的角色槽分别换成"
                            f"{'、'.join(names)}，先复用手动换角链做本地预检；"
                            "预检通过后等你确认，确认前不会调用 NAI。"
                        ),
                        "actions": [
                            {
                                "tool": "batch_generate",
                                "arguments": {
                                    "gallery_id": "site",
                                    "work_ids": [int(work_match.group(1))],
                                    "page_index": 0,
                                    "all_pages": any(
                                        token in text for token in ("全部图片", "所有图片", "每一页", "整套")
                                    ),
                                    "copies_per_work": copies,
                                    "character": {
                                        "mode": "replace_multi",
                                        "replacements": replacements,
                                    },
                                },
                            }
                        ],
                    }
    # A precise source-work + reference-name replacement can be prepared by
    # the same local Remix recipe as the manual tool.  It is safe to bypass
    # the planner only when the user explicitly asks for a draft and negates
    # generation; actual generation still uses the confirmation workflow.
    if "角色资料" in text and "草稿" in text:
        negative_generation = any(token in text for token in ("不要生成", "不生成", "无需生成", "别生成"))
        swap_match = re.search(
            r"(?:把)?(网站|aitag|法典|codex|q群|qq群|qq)?作品[#：:]?(\d+)"
            r"(?:第(\d+)页)?(?:的)?(女性|女|男性|男)?角色(?:换成|替换成|改成)"
            r"(?:nai)?角色资料库?(?:里|里的|中|中的)?(.{1,80}?)(?:，|,|。|$)",
            text,
        )
        if swap_match and negative_generation:
            gallery_id = {
                "": "site", "网站": "site", "aitag": "site", "法典": "codex",
                "codex": "codex", "q群": "qqgroup", "qq群": "qqgroup", "qq": "qqgroup",
            }[swap_match.group(1) or ""]
            gender_text = swap_match.group(4) or ""
            gender = "female" if gender_text in {"女性", "女"} else "male" if gender_text in {"男性", "男"} else ""
            character: dict[str, Any] = {
                "reference_name": swap_match.group(5).strip("的：:,，。"),
                "mode": f"replace_{gender}" if gender else "replace",
                "preserve_action": any(token in text for token in ("保持动作", "保留动作")),
            }
            if gender:
                character["gender"] = gender
            arguments = {
                "gallery_id": gallery_id,
                "work_id": int(swap_match.group(2)),
                "page_index": max(0, int(swap_match.group(3) or 1) - 1),
                "character": character,
            }
            return {
                "reply": (
                    f"好呀，我会用本地资料“{character['reference_name']}”替换作品角色，"
                    "复用手动换角链只准备工作台草稿；不调用模型，也不会生成图片。"
                ),
                "actions": [{"tool": "prepare_remix", "arguments": arguments}],
            }
    if "角色资料" in text and "生成" in text and not any(
        token in text for token in ("不要生成", "不生成", "无需生成", "别生成")
    ):
        batch_match = re.search(
            r"(?:用)?(?:nai)?角色资料库?(?:里|里的|中|中的)?(.{1,80}?)"
            r"(?:替换|换掉|换到)(网站|aitag|法典|codex|q群|qq群|qq)?作品[#：:]?(\d+)"
            r"(?:第(\d+)页)?(?:的)?(女性|女|男性|男)?角色",
            text,
        )
        copies_match = re.search(r"(?:每个作品|每个|每件)?(?:生成|出)(\d{1,2})张", text)
        if batch_match and copies_match:
            copies = int(copies_match.group(1))
            if 1 <= copies <= 20:
                gallery_id = {
                    "": "site", "网站": "site", "aitag": "site", "法典": "codex",
                    "codex": "codex", "q群": "qqgroup", "qq群": "qqgroup", "qq": "qqgroup",
                }[batch_match.group(2) or ""]
                gender_text = batch_match.group(5) or ""
                gender = "female" if gender_text in {"女性", "女"} else "male" if gender_text in {"男性", "男"} else ""
                character: dict[str, Any] = {
                    "reference_name": batch_match.group(1).strip("的：:,，。"),
                    "mode": f"replace_{gender}" if gender else "replace",
                    "preserve_action": any(token in text for token in ("保持动作", "保留动作")),
                }
                if gender:
                    character["gender"] = gender
                work_id = int(batch_match.group(3))
                arguments = {
                    "gallery_id": gallery_id,
                    "work_ids": [work_id],
                    "page_index": max(0, int(batch_match.group(4) or 1) - 1),
                    "copies_per_work": copies,
                    "character": character,
                }
                return {
                    "reply": (
                        f"收到，我会先在本地用资料“{character['reference_name']}”预检 {copies} 张换角任务，"
                        "不调用规划模型；预检通过后仍会等你确认，确认前不会调用 NAI。"
                    ),
                    "actions": [{"tool": "batch_generate", "arguments": arguments}],
                }
    # A precise reference-card handoff is deterministic: resolve a local name,
    # choose a 1-based user slot, and prepare a draft.  Route it before the
    # generic mutation guard so “不要生成图片” does not force an expensive LLM
    # plan.  Ambiguous or generation-requesting wording still falls through.
    if "角色资料" in text and "草稿" in text:
        negative_generation = any(token in text for token in ("不要生成", "不生成", "无需生成", "别生成"))
        actual_generation = "生成" in text and not negative_generation
        name_match = re.search(
            r"(?:nai)?角色资料库?(?:里|里的|中|中的)?(.{1,80}?)(?:，|,)?(?:放到|放进|应用到)",
            text,
        )
        slot_match = re.search(r"角色?槽位?([1-6])", text)
        if name_match and slot_match and not actual_generation:
            name = name_match.group(1).strip("的：:,，")
            prompt_match = re.search(r"准备(?:一个|一份)?(.{0,80}?)(?:工作台|studio)?草稿", text)
            prompt = (prompt_match.group(1) if prompt_match else "").strip("的：:,，")
            arguments: dict[str, Any] = {
                "name": name,
                "slot_index": int(slot_match.group(1)) - 1,
            }
            if prompt:
                arguments["prompt"] = prompt
            return {
                "reply": (
                    f"好呀，我会把本地角色资料“{name}”放进槽位 {int(slot_match.group(1))}，"
                    "只准备工作台草稿，不调用模型，也不会开始生成。"
                ),
                "actions": [{"tool": "prepare_character_reference", "arguments": arguments}],
            }
    if any(name in text for name in ("本地知识库", "软件知识库", "帮助知识库")) and any(
        verb in text for verb in ("更新", "重建", "刷新", "增量")
    ):
        return _knowledge_rebuild_plan()
    mutations = (
        "删除", "移除", "清空", "取消", "加入", "添加", "收藏这个", "启动", "停止",
        "重启", "修改", "配置", "帮我生成", "开始生成", "生成图片", "生成一张", "生成多张",
        "换角", "换画风", "投稿", "上传", "识图", "看图",
    )
    if any(token in text for token in contextual) or any(token in text for token in mutations):
        return None
    routes: list[tuple[tuple[str, ...], str, str]] = [
        (("待生成队列", "待生成清单", "查看待生成"), "list_queue", "我会直接读取本地待生成队列，不调用模型。"),
        (("我的收藏", "收藏列表", "查看收藏"), "list_favorites", "我会直接读取本地收藏，不调用模型。"),
        (("生成结果", "生成成果"), "list_generated", "我会直接读取本地生成成果，不调用模型。"),
        (("采集状态", "爬虫状态"), "inspect_crawler", "我会直接读取本地三图库采集状态，不调用模型。"),
        (("你能做什么", "你会什么", "可用功能", "可用操作", "助手能力"), "inspect_capabilities", "我会直接列出已经接入的本地能力和安全边界，不调用模型。"),
        (("系统运行健康", "运行健康", "服务状态", "系统状态"), "inspect_operations", "我会直接读取本地服务与采集健康状态，不调用模型。"),
        (("生产状态", "生产进度", "生成任务状态", "后处理状态", "投稿准备状态"), "inspect_production", "我会直接读取本地生成、后处理和投稿准备状态，不调用模型。"),
    ]
    for signals, tool, reply in routes:
        if any(signal in text for signal in signals):
            return {"reply": reply, "actions": [{"tool": tool, "arguments": {}}]}

    if "角色资料" in text and any(
        signal in text
        for signal in (
            "有哪些系列",
            "哪些系列",
            "有什么系列",
            "有哪些来源",
            "哪些来源",
            "性别分布",
            "导入状态",
            "资料库状态",
        )
    ):
        return {
            "reply": "我会直接查看本地 NAI 角色资料库的系列、来源和分布，不调用模型。",
            "actions": [{"tool": "inspect_reference_catalog", "arguments": {}}],
        }

    reference_match = re.fullmatch(
        r"(?:搜索|查找|查询|在)?(?:nai)?角色资料(?:库)?(?:里|中)?(?:搜索|查找|查询)?[：:]?(.{1,120})",
        text,
    )
    if reference_match:
        query = reference_match.group(1).strip("：:")
        if query:
            return {
                "reply": f"我会直接在本地 NAI 角色资料库搜索“{query}”，不调用模型。",
                "actions": [{
                    "tool": "search_character_references",
                    "arguments": {"q": query, "limit": 12},
                }],
            }

    style_reference_match = re.fullmatch(
        r"(?:搜索|查找|查询|在)?(?:nai)?(?:画风|画师)资料(?:库)?(?:里|中)?(?:搜索|查找|查询)?[：:]?(.{1,120})",
        text,
    )
    if style_reference_match:
        query = style_reference_match.group(1).strip("：:")
        if query:
            return {
                "reply": f"我会直接在本地 NAI 画风资料库搜索“{query}”，不调用模型。",
                "actions": [{
                    "tool": "search_style_references",
                    "arguments": {"q": query, "limit": 12},
                }],
            }

    search_match = re.fullmatch(r"(?:搜索图库|图库搜索|在图库(?:里|中)?找)[：:]?(.{1,120})", text)
    if search_match:
        query = search_match.group(1).strip("：:")
        if query:
            return {
                "reply": f"我会直接在本地图库搜索“{query}”，不调用模型。",
                "actions": [{"tool": "search_gallery", "arguments": {"q": query, "limit": 12}}],
            }

    work_match = re.fullmatch(
        r"查看(网站|aitag|法典|codex|q群|qq群|qq)作品[#：:]?(\d+)(?:第(\d+)页)?",
        text,
    )
    if work_match:
        gallery_id = {
            "网站": "site", "aitag": "site", "法典": "codex", "codex": "codex",
            "q群": "qqgroup", "qq群": "qqgroup", "qq": "qqgroup",
        }[work_match.group(1)]
        page_number = max(1, int(work_match.group(3) or 1))
        return {
            "reply": "我会按三图库统一身份直接读取这件本地作品，不调用模型。",
            "actions": [{
                "tool": "inspect_work",
                "arguments": {
                    "gallery_id": gallery_id,
                    "work_id": int(work_match.group(2)),
                    "page_index": page_number - 1,
                },
            }],
        }
    return None


async def confirm_butler_action(confirmation_id: str, *, approve: bool) -> dict[str, Any]:
    engine = str(os.environ.get("BUTLER_ENGINE", "langgraph") or "langgraph").lower()
    if engine == "legacy":
        return await legacy.confirm_action(confirmation_id, approve=approve)
    return await _RUNTIME.confirm(confirmation_id, approve=approve)


async def cancel_butler_task(workflow_id: str) -> dict[str, Any]:
    return await _RUNTIME.cancel(workflow_id)


async def resume_butler_task(workflow_id: str) -> dict[str, Any]:
    return await _RUNTIME.resume(workflow_id)


async def retry_butler_task(workflow_id: str) -> dict[str, Any]:
    return await _RUNTIME.retry(workflow_id)


def list_butler_tasks(*, limit: int = 30, status: str = "") -> dict[str, Any]:
    try:
        return {"ok": True, "tasks": _RUNTIME.store.list_tasks(limit=limit, status=status)}
    finally:
        if not _RUNTIME._started:
            _RUNTIME.store.close()


def get_butler_task(workflow_id: str) -> dict[str, Any]:
    try:
        task = _RUNTIME.store.get_task(workflow_id)
        if not task:
            raise ValueError("管家任务不存在")
        return {"ok": True, "task": task}
    finally:
        if not _RUNTIME._started:
            _RUNTIME.store.close()


def butler_task_revision() -> int:
    return _RUNTIME.store.task_revision()


def wait_for_butler_task_change(after_revision: int, *, timeout: float = 15.0) -> int:
    return _RUNTIME.store.wait_for_task_change(after_revision, timeout=timeout)


def list_butler_messages(*, limit: int = 60, before_id: int | None = None) -> dict[str, Any]:
    count = max(1, min(int(limit), 100))
    try:
        rows = _RUNTIME.store.list_messages(limit=count + 1, before_id=before_id)
        has_more = len(rows) > count
        if has_more:
            rows = rows[-count:]
        return {"ok": True, "messages": rows, "has_more": has_more}
    finally:
        if not _RUNTIME._started:
            _RUNTIME.store.close()


def clear_butler_messages() -> dict[str, Any]:
    try:
        return {"ok": True, "deleted": _RUNTIME.store.clear_messages()}
    finally:
        if not _RUNTIME._started:
            _RUNTIME.store.close()


def workflow_runtime_status() -> dict[str, Any]:
    try:
        return _RUNTIME.status()
    finally:
        if not _RUNTIME._started:
            _RUNTIME.store.close()

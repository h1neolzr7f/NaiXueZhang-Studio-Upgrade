"""LLM prompt optimization for NovelAI generation (NAI-friendly style, not rigid schema)."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

from nai_prompt_playbook import apply_playbook_to_comment_texts, playbook_optimizer_rules
from nai_prompt_profiles import (
    PROFILE_ANIMA_EPIC,
    PROFILE_ANIMA_FAITHFUL,
    apply_prompt_profile_to_comment,
    normalize_prompt_profile,
)
from pixiv_launch import _ai_env, _chat_completion, _extract_json_block, load_config, normalize_ai_config

OPTIMIZE_SYSTEM = """你是 NovelAI 资深咒语顾问。任务：把用户给出的绘图咒语改写成「更适合 NovelAI 模型出图」的版本。

目标：提升出图质量（构图、角色清晰度、标签有效性、负面词针对性），不是套用固定模板。

输出要求：
- 只返回一个 JSON 对象，不要 Markdown，不要解释性段落。
- 字段：
  - prompt: 主提示词文本（Danbooru 风格 tag + 必要时少量自然语言，逗号或换行均可）
  - uc: 负面提示词文本
  - char_captions: 可选数组，多角色时按槽位给出各角色咒语；单角色可省略或空数组
  - base_caption: 可选，场景/基底咒语（多角色 v4 时分区时使用）
  - notes: 可选，一句话说明改动要点（≤80字）

硬规则：
- 面向 NovelAI / nai-diffusion，不要 SD/ComfyUI/LoRA 语法。
- 保留原图核心意图：角色、动作、构图、氛围不要乱改。
- 去掉重复、冲突、无意义 tag；适度补强质量与光照，不要堆砌 score_9 类垃圾 tag。
- 多角色时 char_captions 数量与输入一致，不要合并角色。
- 不要输出 steps/seed/width 等参数。
- 允许灵活文本风格，不必死磕某种社区格式。
""" + playbook_optimizer_rules()


def _prompt_snapshot(comment: dict[str, Any]) -> dict[str, Any]:
    comment = comment or {}
    v4 = comment.get("v4_prompt") or {}
    cap = (v4.get("caption") or {}) if isinstance(v4, dict) else {}
    char_caps = cap.get("char_captions") or []
    chars: list[str] = []
    if isinstance(char_caps, list):
        for item in char_caps:
            if isinstance(item, dict):
                chars.append(str(item.get("char_caption") or "").strip())
    base = str(cap.get("base_caption") or comment.get("prompt") or "").strip()
    return {
        "prompt": str(comment.get("prompt") or base).strip(),
        "base_caption": base,
        "uc": str(comment.get("uc") or "").strip(),
        # Slot position is part of the NAI V4 contract.  Keep empty
        # placeholders so applying a reference to slot 2 does not silently
        # collapse it into slot 1 in Studio/Butler round-trips.
        "char_captions": chars,
    }


def _apply_texts_to_comment(comment: dict[str, Any], texts: dict[str, Any]) -> dict[str, Any]:
    patched = copy.deepcopy(comment or {})
    prompt = str(texts.get("prompt") or "").strip()
    uc = str(texts.get("uc") if texts.get("uc") is not None else patched.get("uc") or "").strip()
    base = str(texts.get("base_caption") or prompt).strip()
    char_caps_in = texts.get("char_captions")
    if isinstance(char_caps_in, list) and char_caps_in:
        v4 = patched.setdefault("v4_prompt", {})
        if not isinstance(v4, dict):
            v4 = {}
            patched["v4_prompt"] = v4
        cap = v4.setdefault("caption", {})
        if not isinstance(cap, dict):
            cap = {}
            v4["caption"] = cap
        existing = cap.get("char_captions") or []
        merged: list[dict[str, Any]] = []
        for i, raw in enumerate(char_caps_in):
            text = str(raw or "").strip()
            old = existing[i] if i < len(existing) and isinstance(existing[i], dict) else {}
            center = old.get("center") or old.get("centers")
            if isinstance(center, list) and center:
                centers = center
            elif isinstance(center, dict):
                centers = [center]
            else:
                centers = [{"x": 0.5, "y": 0.5}]
            merged.append({"char_caption": text, "centers": centers})
        cap["char_captions"] = merged
        cap["base_caption"] = base
        patched["prompt"] = base or prompt
    else:
        patched["prompt"] = prompt or base
        v4 = patched.get("v4_prompt")
        if isinstance(v4, dict):
            cap = v4.get("caption")
            if isinstance(cap, dict) and base:
                cap["base_caption"] = base
    if uc:
        patched["uc"] = uc
    return patched


def _local_optimize(comment: dict[str, Any], *, profile: str) -> dict[str, Any]:
    profile_id = normalize_prompt_profile(profile)
    if profile_id in {PROFILE_ANIMA_FAITHFUL, PROFILE_ANIMA_EPIC}:
        patched, info = apply_prompt_profile_to_comment(comment, profile_id)
        snap = _prompt_snapshot(patched)
        return {
            "ok": True,
            "provider": "local",
            "profile": profile_id,
            "label": info.get("label") or profile_id,
            "texts": snap,
            "comment": patched,
            "notes": "本地 Anima 风格预设（可选资产）",
        }
    snap = _prompt_snapshot(comment)
    return {
        "ok": True,
        "provider": "local",
        "profile": "native",
        "label": "保持原样",
        "texts": snap,
        "comment": copy.deepcopy(comment),
        "notes": "",
    }


def _apply_playbook_result(
    comment: dict[str, Any],
    texts: dict[str, Any],
    *,
    intent: str = "",
    provider: str,
    profile: str,
    label: str,
    before: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = apply_playbook_to_comment_texts(texts, intent=intent)
    patched = _apply_texts_to_comment(comment, report["texts"])
    payload = {
        "ok": True,
        "provider": provider,
        "profile": profile,
        "label": label,
        "texts": _prompt_snapshot(patched),
        "comment": patched,
        "notes": str((extra or {}).get("notes") or report.get("notes") or "").strip(),
        "playbook": {
            "demand": report.get("demand"),
            "outfit_override": report.get("outfit_override"),
            "copyright_minimal": report.get("copyright_minimal"),
            "stripped": report.get("stripped") or [],
            "moved_to_slots": report.get("moved_to_slots") or [],
            "moved_to_base": report.get("moved_to_base") or [],
            "notes": report.get("notes") or "",
        },
    }
    if before is not None:
        payload["before"] = before
    if extra:
        for key, value in extra.items():
            if key != "notes":
                payload[key] = value
    return payload


def optimize_nai_prompt(
    comment: dict[str, Any],
    *,
    mode: str = "smart",
    profile: str = "",
    intent: str = "",
) -> dict[str, Any]:
    """Optimize prompt for better NAI results. mode: smart | local | playbook | anima_*."""
    comment = copy.deepcopy(comment or {})
    mode_key = str(mode or "smart").strip().lower()
    if mode_key in {"local", "native", "none"}:
        return _local_optimize(comment, profile="native")
    if mode_key in {"playbook", "v5", "slot"}:
        before = _prompt_snapshot(comment)
        return _apply_playbook_result(
            comment,
            before,
            intent=intent,
            provider="local",
            profile="v5_playbook",
            label="V5 槽位整理",
            before=before,
        )
    if mode_key in {"anima", "anima_faithful", "anima_v1", "faithful"}:
        return _local_optimize(comment, profile=PROFILE_ANIMA_FAITHFUL)
    if mode_key in {"anima_epic", "anima_v2", "epic"}:
        return _local_optimize(comment, profile=PROFILE_ANIMA_EPIC)
    if profile:
        prof = normalize_prompt_profile(profile)
        if prof not in {"native", ""}:
            return _local_optimize(comment, profile=prof)

    cfg = load_config()
    env = _ai_env(cfg)
    if not env.get("api_key"):
        raise ValueError("未配置 AI API Key，请在设置中填写 data/ai.local.json 或通过 /pixiv 配置")

    before = _prompt_snapshot(comment)
    user_payload = {
        "task": "optimize_nai_prompt",
        "mode": mode_key,
        "original": before,
        "hints": {
            "model_family": "novelai_nai_diffusion_v4",
            "keep_char_slot_count": len(before.get("char_captions") or []),
        },
    }
    raw = _chat_completion(env, OPTIMIZE_SYSTEM, user_payload)
    try:
        parsed = _extract_json_block(raw)
    except Exception as exc:
        raise ValueError(f"AI 优化返回无法解析: {exc}") from exc

    texts = {
        "prompt": str(parsed.get("prompt") or before.get("prompt") or "").strip(),
        "uc": str(parsed.get("uc") if parsed.get("uc") is not None else before.get("uc") or "").strip(),
        "base_caption": str(parsed.get("base_caption") or parsed.get("prompt") or before.get("base_caption") or "").strip(),
        "char_captions": parsed.get("char_captions") if isinstance(parsed.get("char_captions"), list) else before.get("char_captions"),
    }
    ai_cfg = normalize_ai_config(cfg.get("ai") or {})
    return _apply_playbook_result(
        comment,
        texts,
        intent=intent,
        provider="llm",
        profile="nai_smart",
        label="智能优化",
        before=before,
        extra={
            "notes": str(parsed.get("notes") or "").strip(),
            "model": ai_cfg.get("model") or "",
        },
    )


def ai_status() -> dict[str, Any]:
    cfg = load_config()
    env = _ai_env(cfg)
    return {
        "has_api_key": bool(env.get("api_key")),
        "provider": str(env.get("provider") or ""),
        "model": str(env.get("model") or ""),
        "api_base": str(env.get("api_base") or ""),
    }

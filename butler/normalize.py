"""Butler normalize implementation."""

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


def _normalize_studio_args(args: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"gallery_id": api._gallery_id(args.get("gallery_id"))}
    work_id = api._int_value(
        args.get("work_id"),
        name="work_id",
        minimum=1,
        maximum=2**63 - 1,
    )
    if work_id:
        normalized["work_id"] = work_id
    normalized["page_index"] = api._int_value(
        args.get("page_index"),
        name="page_index",
        minimum=0,
        maximum=999,
        default=0,
    )
    prompt = api._clean_text(args.get("prompt"), limit=8000)
    uc = api._clean_text(args.get("uc", args.get("negative_prompt")), limit=4000)
    if prompt:
        normalized["prompt"] = prompt
    if uc:
        normalized["uc"] = uc

    for name in ("width", "height"):
        value = api._int_value(
            args.get(name), name=name, minimum=256, maximum=2048
        )
        if value is not None:
            if value % 64:
                raise ValueError(f"{name} 必须是 64 的倍数")
            normalized[name] = value
    if normalized.get("width") and normalized.get("height"):
        if int(normalized["width"]) * int(normalized["height"]) > 2_400_000:
            raise ValueError("图片总像素过高，请控制在 240 万像素以内")

    steps = api._int_value(args.get("steps"), name="steps", minimum=1, maximum=50)
    scale = api._float_value(args.get("scale"), name="scale", minimum=0.0, maximum=10.0)
    seed = api._int_value(
        args.get("seed"), name="seed", minimum=0, maximum=2**32 - 1
    )
    batch = api._int_value(
        args.get("batch_count", args.get("batch")),
        name="batch_count",
        minimum=1,
        maximum=20,
        default=1,
    )
    if steps is not None:
        normalized["steps"] = steps
    if scale is not None:
        normalized["scale"] = scale
    if seed is not None:
        normalized["seed"] = seed
    normalized["batch_count"] = batch

    sampler = api._clean_text(args.get("sampler"), limit=80)
    if sampler:
        allowed = set(api.studio_config().get("samplers") or [])
        if sampler not in allowed:
            raise ValueError(f"不支持的 sampler：{sampler}")
        normalized["sampler"] = sampler
    return normalized



def _normalize_batch_args(args: dict[str, Any]) -> dict[str, Any]:
    gallery_id = api._gallery_id(args.get("gallery_id"))
    work_refs: list[dict[str, Any]] = []
    if args.get("work_ids") is not None or args.get("work_id") is not None:
        work_refs = [
            {"gallery_id": gallery_id, "work_id": work_id}
            for work_id in api._work_ids(args.get("work_ids", args.get("work_id")))
        ]
    elif bool(args.get("use_queue")):
        from production_queue import list_refs

        work_refs = [
            {
                "gallery_id": api._gallery_id(item.get("gallery_id")),
                "work_id": int(item.get("work_id") or 0),
            }
            for item in list_refs()
            if int(item.get("work_id") or 0) > 0
        ]
    else:
        q = api._clean_text(args.get("q"), limit=300)
        search_prompt = api._clean_text(args.get("search_prompt", args.get("prompt")), limit=1000)
        limit = int(
            api._int_value(args.get("limit"), name="limit", minimum=1, maximum=50, default=12)
            or 12
        )
        if q or search_prompt:
            # Preserve the original site-gallery singleton contract (including
            # test/extension patch points) while routing external galleries
            # through the new catalog.
            db = api.DB if gallery_id == "site" else api.get_db(gallery_id)
            data = db.search_works(
                q=q,
                prompt=search_prompt,
                page=1,
                page_size=limit,
                sort=api._clean_text(args.get("sort"), limit=20) or "new",
                time_range=api._clean_text(args.get("time_range"), limit=20) or "all",
                local_scope=api.GALLERY_SCOPE if gallery_id == "site" and api.GALLERY_LOCAL_ONLY else "",
                skip_total=True,
                nai_only=True,
            )
            work_refs = [
                {"gallery_id": gallery_id, "work_id": int(item.get("id") or 0)}
                for item in (data.get("items") or [])
                if int(item.get("id") or 0) > 0
            ]
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in work_refs:
        ref = api.WorkRef.parse(item["work_id"], item.get("gallery_id"))
        if ref.key not in seen:
            deduped.append({"gallery_id": ref.gallery_id, "work_id": int(ref.work_id)})
            seen.add(ref.key)
    work_refs = deduped[:50]
    if not work_refs:
        raise ValueError("批量生成需要作品 ID、待生成队列或可命中的查询条件")
    copies = int(
        api._int_value(
            args.get("copies_per_work"),
            name="copies_per_work",
            minimum=1,
            maximum=20,
            default=1,
        )
        or 1
    )
    if len(work_refs) * copies > 200:
        raise ValueError("一次管家批量任务最多生成 200 张")

    studio_input = {
        key: args.get(key)
        for key in ("width", "height", "steps", "scale", "sampler", "seed")
        if args.get(key) is not None
    }
    if args.get("prompt_override"):
        studio_input["prompt"] = args.get("prompt_override")
    if args.get("uc") or args.get("negative_prompt"):
        studio_input["uc"] = args.get("uc", args.get("negative_prompt"))
    studio_args = api._normalize_studio_args(studio_input)
    studio_args.pop("page_index", None)
    studio_args.pop("batch_count", None)
    return {
        "gallery_id": gallery_id,
        "work_ids": [item["work_id"] for item in work_refs],
        "work_refs": work_refs,
        "page_index": int(
            api._int_value(args.get("page_index"), name="page_index", minimum=0, maximum=999, default=0)
            or 0
        ),
        "all_pages": bool(args.get("all_pages", False)),
        "copies_per_work": copies,
        "generation": studio_args,
        "extra": api._clean_text(args.get("extra"), limit=1000),
    }



def _normalize_pixiv_prepare_args(args: dict[str, Any]) -> dict[str, Any]:
    raw_ids = args.get("group_ids")
    group_ids: list[str] = []
    if isinstance(raw_ids, list):
        for value in raw_ids[:20]:
            group_id = api._clean_text(value, limit=120)
            if group_id and group_id not in group_ids:
                group_ids.append(group_id)
    elif raw_ids:
        group_ids = [api._clean_text(raw_ids, limit=120)]
    if not group_ids:
        from pixiv_launch import list_launch_groups

        latest_count = int(
            api._int_value(
                args.get("latest_count"),
                name="latest_count",
                minimum=1,
                maximum=20,
                default=1,
            )
            or 1
        )
        group_ids = [
            str(item.get("group_id") or "")
            for item in list_launch_groups()[:latest_count]
            if str(item.get("group_id") or "")
        ]
    if not group_ids:
        raise ValueError("没有可用于投稿准备的生成系列")
    return {
        "group_ids": group_ids,
        "merge_groups": True,
        "extra": api._clean_text(args.get("extra"), limit=1000),
    }



def _has_remix_arguments(args: dict[str, Any]) -> bool:
    return any(
        args.get(key) not in (None, "", {})
        for key in (
            "character",
            "style",
            "character_preset_id",
            "source_work_id",
            "custom_char_caption",
            "style_find",
            "style_replace",
            "style_append",
            "style_preset_id",
            "style_name",
            "reference_id",
            "reference_name",
        )
    )



def _normalize_remix(args: dict[str, Any]) -> dict[str, Any]:
    from butler.remix import normalize_remix_recipe

    prepared = copy.deepcopy(args)
    character = prepared.get("character") or {}
    if not isinstance(character, dict):
        raise ValueError("character 必须是对象")
    reference_id = api._clean_text(
        character.get("reference_id", prepared.get("reference_id")), limit=80
    )
    reference_name = api._clean_text(
        character.get("reference_name", prepared.get("reference_name")), limit=300
    )
    reference: dict[str, Any] | None = None
    if reference_id or reference_name:
        if any(
            character.get(key) not in (None, "")
            for key in ("preset_id", "source_work_id", "custom_char_caption")
        ):
            raise ValueError("资料库角色不能同时指定手动预设、来源作品或自定义角色咒语")
        resolved_id, _ = api._resolve_character_reference(
            {
                "reference_id": reference_id,
                "name": reference_name,
                "source": character.get("reference_source", prepared.get("reference_source")),
            }
        )
        item = api.get_reference_catalog().get(resolved_id)
        if item is None:
            raise ValueError("指定的 NAI 角色资料不存在")
        caption = api._clean_text(item.get("character_caption"), limit=8000)
        if not caption:
            raise ValueError("指定的 NAI 角色资料缺少可用角色标签")
        character["custom_char_caption"] = caption
        gender = api._clean_text(item.get("gender"), limit=20).lower()
        if gender in {"male", "female"} and not character.get("gender"):
            character["gender"] = gender
        prepared["character"] = character
        reference = {
            "reference_id": resolved_id,
            "label": str(item.get("label") or reference_name),
            "source": str(item.get("source") or ""),
            "source_id": str(item.get("source_id") or ""),
            "copyright": str(item.get("copyright") or ""),
            "provenance": copy.deepcopy(item.get("provenance") or {}),
        }

    recipe = normalize_remix_recipe(prepared)
    if reference:
        recipe.setdefault("transform", {})["reference"] = reference
    return recipe



def _studio_generation_settings(args: dict[str, Any]) -> dict[str, Any]:
    return {
        key: args[key]
        for key in ("prompt", "uc", "width", "height", "steps", "scale", "sampler", "seed")
        if key in args
    }



def _resolve_character_reference(args: dict[str, Any]) -> tuple[str, str]:
    """Resolve a model-provided local name to one stable catalog identity."""

    catalog = api.get_reference_catalog()
    reference_id = api._clean_text(args.get("reference_id"), limit=80)
    if reference_id:
        item = catalog.get(reference_id)
        if item is None:
            raise ValueError("指定的 NAI 角色资料不存在")
        return reference_id, api._clean_text(item.get("label"), limit=300)

    name = api._clean_text(args.get("name", args.get("character_name")), limit=300)
    if not name:
        raise ValueError("prepare_character_reference 需要 reference_id 或角色名")
    result = catalog.search(
        query=name,
        source=api._clean_text(args.get("source"), limit=80),
        limit=12,
    )
    items = list(result.get("items") or [])
    wanted = name.casefold()
    exact = [
        item
        for item in items
        if wanted
        in {
            str(item.get("label") or "").casefold(),
            str(item.get("source_id") or "").casefold(),
            str(item.get("trigger") or "").casefold(),
        }
    ]
    matches = exact or items
    if not matches:
        raise ValueError(f"NAI 角色资料库中没有找到“{name}”")
    if len(matches) > 1 and not exact:
        labels = "、".join(str(item.get("label") or item.get("source_id")) for item in matches[:5])
        raise ValueError(f"角色名“{name}”有多个候选：{labels}；请给出更准确名称")
    item = matches[0]
    return str(item["reference_id"]), str(item.get("label") or name)



def normalize_action(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("工具动作必须是对象")
    tool = api._clean_text(raw.get("tool", raw.get("name")), limit=80)
    if tool not in api._TOOL_BY_NAME:
        raise ValueError(f"工具不在白名单：{tool or '空'}")
    if tool in {"start_crawler", "configure_crawler"} and api._main_gallery_empty():
        raise ValueError(api.EMPTY_GALLERY_CRAWL_MSG)
    args = raw.get("arguments", raw.get("args", {}))
    if not isinstance(args, dict):
        raise ValueError("arguments 必须是对象")

    if tool in {"search_gallery", "audit_gallery"}:
        sort = api._clean_text(args.get("sort"), limit=20) or "new"
        time_range = api._clean_text(args.get("time_range"), limit=20) or "all"
        if sort not in {"new", "monthly", "count"}:
            raise ValueError("sort 不受支持")
        if time_range not in {"all", "day", "week", "month", "year"}:
            raise ValueError("time_range 不受支持")
        normalized_args = {
            "gallery_id": api._gallery_id(args.get("gallery_id")),
            "q": api._clean_text(args.get("q"), limit=300),
            "prompt": api._clean_text(args.get("prompt"), limit=1000),
            "sort": sort,
            "time_range": time_range,
            "limit": api._int_value(
                args.get("limit"), name="limit", minimum=1, maximum=12, default=6
            ),
        }
        if tool == "audit_gallery":
            normalized_args["use_vision"] = bool(args.get("use_vision", False))
    elif tool == "compare_gallery_candidates":
        raw_candidates = args.get("candidates")
        if not isinstance(raw_candidates, list) or not 2 <= len(raw_candidates) <= 4:
            raise ValueError("固定候选集需要 2 到 4 张图片")
        candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, dict):
                raise ValueError("候选图片引用必须是对象")
            gallery_id = api._gallery_id(raw_candidate.get("gallery_id"))
            work_id = api._int_value(
                raw_candidate.get("work_id"),
                name="work_id",
                minimum=1,
                maximum=2**63 - 1,
            )
            page_index = api._int_value(
                raw_candidate.get("page_index"),
                name="page_index",
                minimum=0,
                maximum=999,
                default=0,
            )
            if not work_id:
                raise ValueError("候选图片缺少 work_id")
            identity = (gallery_id, int(work_id), int(page_index))
            if identity in seen:
                raise ValueError("固定候选集中不能重复加入同一张图片")
            seen.add(identity)
            candidates.append(
                {
                    "gallery_id": gallery_id,
                    "work_id": int(work_id),
                    "page_index": int(page_index),
                }
            )
        normalized_args = {
            "question": api._clean_text(args.get("question"), limit=300)
            or "这些候选中哪张整体视觉效果更好？",
            "candidates": candidates,
            # This capability can only be reached through an explicit compare
            # intent or button; planners cannot silently widen the boundary.
            "use_vision": True,
        }
    elif tool == "inspect_work":
        normalized_args = {
            "gallery_id": api._gallery_id(args.get("gallery_id")),
            "work_id": api._int_value(
                args.get("work_id"),
                name="work_id",
                minimum=1,
                maximum=2**63 - 1,
            ),
            "page_index": api._int_value(
                args.get("page_index"),
                name="page_index",
                minimum=0,
                maximum=999,
                default=0,
            ),
        }
        if not normalized_args["work_id"]:
            raise ValueError("work_id 是必填项")
    elif tool == "list_queue":
        normalized_args = {
            "limit": api._int_value(
                args.get("limit"), name="limit", minimum=1, maximum=40, default=12
            )
        }
    elif tool == "search_character_references":
        gender = api._clean_text(args.get("gender"), limit=20).lower()
        if gender not in {"", "female", "male", "other", "unknown"}:
            raise ValueError("gender 不受支持")
        normalized_args = {
            "q": api._clean_text(args.get("q", args.get("name")), limit=300),
            "gender": gender,
            "copyright": api._clean_text(args.get("copyright"), limit=300),
            "source": api._clean_text(args.get("source"), limit=80),
            "limit": api._int_value(
                args.get("limit"), name="limit", minimum=1, maximum=20, default=8
            ),
        }
    elif tool == "search_style_references":
        kind = api._clean_text(args.get("kind"), limit=20).lower()
        if kind not in {"", "artist", "style"}:
            raise ValueError("kind 只支持 artist 或 style")
        normalized_args = {
            "q": api._clean_text(args.get("q", args.get("name")), limit=300),
            "kind": kind,
            "source": api._clean_text(args.get("source"), limit=80),
            "limit": api._int_value(
                args.get("limit"), name="limit", minimum=1, maximum=20, default=8
            ),
        }
    elif tool in {"inspect_reference_catalog", "rebuild_knowledge_catalog"}:
        normalized_args = {}
    elif tool == "prepare_character_reference":
        normalized_args = api._normalize_studio_args(args)
        reference_id, reference_label = api._resolve_character_reference(args)
        normalized_args["reference_id"] = reference_id
        normalized_args["reference_label"] = reference_label
        normalized_args["slot_index"] = api._int_value(
            args.get("slot_index"), name="slot_index", minimum=0, maximum=5, default=0
        )
        model = api._clean_text(args.get("model"), limit=120) or "nai-diffusion-4-5-full"
        if not model.startswith("nai-diffusion-"):
            raise ValueError("model 必须是 NovelAI 图像模型")
        normalized_args["model"] = model
    elif tool in {"prepare_studio", "generate_image"}:
        normalized_args = api._normalize_studio_args(args)
        if not normalized_args.get("work_id") and not normalized_args.get("prompt"):
            raise ValueError(f"{tool} 需要 work_id 或 prompt")
        if api._has_remix_arguments(args):
            if not normalized_args.get("work_id"):
                raise ValueError("换角/换画风必须指定图库作品 work_id")
            normalized_args["remix_recipe"] = api._normalize_remix(args)
            normalized_args["generation"] = api._studio_generation_settings(normalized_args)
            if tool == "generate_image":
                work_id = int(normalized_args["work_id"])
                gallery_id = api._gallery_id(normalized_args.get("gallery_id"))
                normalized_args = {
                    "gallery_id": gallery_id,
                    "work_ids": [work_id],
                    "work_refs": [{"gallery_id": gallery_id, "work_id": work_id}],
                    "page_index": int(normalized_args.get("page_index") or 0),
                    "all_pages": bool(args.get("all_pages", False)),
                    "copies_per_work": int(normalized_args.get("batch_count") or 1),
                    "generation": dict(normalized_args.get("generation") or {}),
                    "remix_recipe": normalized_args["remix_recipe"],
                    "extra": "",
                }
                tool = "batch_generate"
    elif tool == "prepare_remix":
        normalized_args = api._normalize_studio_args(args)
        if not normalized_args.get("work_id"):
            raise ValueError("prepare_remix 必须指定 work_id")
        normalized_args["remix_recipe"] = api._normalize_remix(args)
        normalized_args["generation"] = api._studio_generation_settings(normalized_args)
    elif tool in {"batch_generate", "batch_generate_and_prepare_pixiv"}:
        normalized_args = api._normalize_batch_args(args)
        if api._has_remix_arguments(args):
            normalized_args["remix_recipe"] = api._normalize_remix(args)
    elif tool == "batch_director":
        from nai_director import normalize_director_recipe, normalize_director_sources

        raw_sources = args.get("sources")
        if not isinstance(raw_sources, list):
            raise ValueError("batch_director 需要精确图片 sources 数组")
        raw_recipe = args.get("recipe")
        if not isinstance(raw_recipe, dict):
            raise ValueError("batch_director 需要 recipe 对象")
        normalized_args = {
            "sources": normalize_director_sources(raw_sources),
            "recipe": normalize_director_recipe(raw_recipe),
        }
    elif tool == "prepare_pixiv_submission":
        normalized_args = api._normalize_pixiv_prepare_args(args)
    elif tool == "inspect_production":
        normalized_args = {
            "limit": api._int_value(
                args.get("limit"), name="limit", minimum=1, maximum=20, default=5
            )
        }
    elif tool == "inspect_operations":
        normalized_args = {}
    elif api.handles_gallery_operation(tool):
        normalized_args = api.normalize_gallery_operation(tool, args)
    elif tool in {"add_to_queue", "remove_from_queue"}:
        gallery_id, work_ids = api.resolve_work_selection(args)
        normalized_args = {
            "gallery_id": gallery_id,
            "work_ids": work_ids,
        }
        if tool == "add_to_queue":
            normalized_args["note"] = api._clean_text(args.get("note"), limit=240)
    elif tool == "configure_crawler":
        if args.get("proxy_url") not in (None, ""):
            raise ValueError(api.SETTINGS_ENDPOINT_HINT)
        normalized_args = {}
        for key in (
            "enabled",
            "source_mode",
            "search_queries",
            "user_ids",
            "rankings",
            "request_delay_sec",
            "browser_mode",
        ):
            if key in args:
                normalized_args[key] = args[key]
    elif tool == "modify_setting":
        forbidden = {"ai_api_base", "api_base", "proxy_url", "port"}
        hit = [key for key in forbidden if args.get(key) not in (None, "")]
        normalized_args: dict[str, Any] = {}
        if args.get("ai_model") not in (None, ""):
            normalized_args["ai_model"] = str(args.get("ai_model"))
        for key in (
            "enabled",
            "source_mode",
            "search_queries",
            "user_ids",
            "rankings",
            "request_delay_sec",
            "browser_mode",
            "watch_interval_sec",
        ):
            if key in args:
                normalized_args[key] = args[key]
        if hit and not normalized_args:
            raise ValueError(api.SETTINGS_ENDPOINT_HINT)
        if hit:
            normalized_args["_forbidden_setting_hint"] = api.SETTINGS_ENDPOINT_HINT
        if not normalized_args:
            raise ValueError("没有可修改的白名单配置项。" + api.SETTINGS_ENDPOINT_HINT)
        crawler_args = {
            key: value
            for key, value in normalized_args.items()
            if key != "_forbidden_setting_hint"
        }
        if api._crawler_mutation_blocked_when_empty(crawler_args):
            raise ValueError(api.EMPTY_GALLERY_CRAWL_MSG)
    elif tool == "set_auto_mode":
        if "auto_mode" not in args:
            raise ValueError("auto_mode 是必填项")
        normalized_args = {
            "auto_mode": bool(args.get("auto_mode")),
            "auto_repair": bool(args.get("auto_repair", False)),
        }
    else:
        normalized_args = {}
    return {
        "tool": tool,
        "arguments": normalized_args,
        "risk": api._TOOL_BY_NAME[tool]["risk"],
        "label": api._TOOL_BY_NAME[tool]["label"],
    }


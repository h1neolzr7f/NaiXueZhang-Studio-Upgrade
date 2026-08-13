"""Standalone, durable batch workflow for NovelAI Director Tools."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import io
import json
import re
import secrets
import threading
import time
import warnings
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageOps, UnidentifiedImageError

from gallery_catalog import GALLERY_IDS, get_db, get_spec, normalize_gallery_id
from generated_gallery import get_group, list_groups, scan_all_items
from generation_jobs import (
    GenerationJob,
    GenerationJobManager,
    JobAlreadyRunning,
    JobPersistenceError,
    partition_retry_targets,
)
from nai_api import call_nai_director, novelai_director_status
from paths import canonical_path, data_dir, path_is_within, relative_to_canonical, seed_data_file


MAX_SOURCES = 40
MAX_OUTPUTS = 120
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_SOURCE_PIXELS = 80_000_000
PREVIEW_TTL_SECONDS = 10 * 60
DIRECTOR_STATE_PATH = data_dir() / "director_jobs.local.json"
DIRECTOR_OUTPUT_DIR = data_dir() / "generated"
_PREVIEW_SECRET = secrets.token_bytes(32)
_GENERATED_ID_RE = re.compile(r"^\d{8}_\d{6}(?:_\d+)?$")
_JOB_MANAGER = GenerationJobManager(
    max_history=48,
    cancel_poll_interval=0.05,
    state_path=DIRECTOR_STATE_PATH,
)
_TASK: asyncio.Task[None] | None = None
_SOURCE_CACHE_LOCK = threading.Lock()
_SOURCE_ENCODE_CACHE: OrderedDict[
    tuple[str, int, int], tuple[str, int, int, str]
] = OrderedDict()
_SOURCE_RAW_HASH_CACHE: OrderedDict[tuple[str, int, int], str] = OrderedDict()
_SOURCE_CACHE_MAX_ITEMS = 8


def _load_director_catalog() -> dict[str, Any]:
    path = seed_data_file("director_catalog.json")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RuntimeError(f"缺少导演目录数据文件：{path}") from None


_DIRECTOR_CATALOG = _load_director_catalog()
_TOOLS: tuple[dict[str, Any], ...] = tuple(_DIRECTOR_CATALOG["tools"])
_TOOLS_BY_ID = {item["id"]: item for item in _TOOLS}
_EMOTIONS = tuple(_DIRECTOR_CATALOG["emotions"])


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").replace("\x00", "").strip()[:limit]


def _director_level(value: Any, *, default: int, label: str) -> int:
    candidate = default if value in (None, "") else value
    if isinstance(candidate, bool):
        raise ValueError(f"{label} 必须是 0–5 的整数")
    try:
        parsed = int(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 0–5 的整数") from exc
    if isinstance(candidate, float) and not candidate.is_integer():
        raise ValueError(f"{label} 必须是 0–5 的整数")
    return max(0, min(parsed, 5))


def director_catalog() -> dict[str, Any]:
    return {
        "ok": True,
        "feature": "nai_batch_director",
        "standalone": True,
        "provider": "novelai",
        "endpoint": "/ai/augment-image",
        "official_docs": "https://docs.novelai.net/en/image/directortools/",
        "tools": copy.deepcopy(list(_TOOLS)),
        "emotions": list(_EMOTIONS),
        "max_sources": MAX_SOURCES,
        "max_outputs": MAX_OUTPUTS,
        "concurrency": 1,
        "requires_explicit_confirmation": True,
        "billing": {
            "anlas": "unknown",
            "message": "导演工具费用由 NovelAI 账号与上游规则决定，提交前不会宣称免费。",
        },
        "readiness": novelai_director_status(),
    }


def normalize_director_recipe(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(raw or {})
    tool_id = _text(source.get("tool"), 40).lower().replace("-", "_")
    spec = _TOOLS_BY_ID.get(tool_id)
    if spec is None:
        raise ValueError(f"unknown director tool: {tool_id or '(empty)'}")
    recipe: dict[str, Any] = {
        "tool": tool_id,
        "req_type": spec["req_type"],
    }
    if tool_id == "colorize":
        prompt = _text(source.get("prompt"), 500)
        defry = _director_level(source.get("defry"), default=0, label="Defry")
        if prompt:
            recipe["prompt"] = prompt
        recipe["defry"] = defry
    elif tool_id == "emotion":
        emotion = _text(source.get("emotion"), 40).lower()
        if not emotion and _text(source.get("req_type"), 40) == "emotion":
            normalized_prompt = _text(source.get("prompt"), 500)
            if not normalized_prompt:
                raise ValueError("emotion Director recipe is missing its normalized prompt")
            recipe["prompt"] = normalized_prompt
            recipe["defry"] = _director_level(source.get("defry"), default=3, label="表情强度")
            recipe["outputs_per_source"] = int(spec["outputs_per_source"])
            return recipe
        if emotion not in _EMOTIONS:
            raise ValueError("emotion must be selected from the supported list")
        extra_prompt = _text(source.get("prompt"), 460)
        recipe["prompt"] = f"{emotion}, {extra_prompt}" if extra_prompt else emotion
        recipe["defry"] = _director_level(source.get("level"), default=3, label="表情强度")
    recipe["outputs_per_source"] = int(spec["outputs_per_source"])
    return recipe


def _source_identity(raw: dict[str, Any]) -> str:
    kind = _text(raw.get("kind"), 20).lower()
    if kind == "generated":
        image_id = Path(_text(raw.get("image_id"), 80)).stem
        if not _GENERATED_ID_RE.fullmatch(image_id):
            raise ValueError("invalid generated image identity")
        return f"generated:{image_id}"
    if kind == "gallery":
        gallery_id = _text(raw.get("gallery_id") or "site", 20).lower()
        if gallery_id not in GALLERY_IDS:
            raise ValueError(f"unknown gallery identity: {gallery_id}")
        try:
            work_id = int(raw.get("work_id") or 0)
            page_index = int(raw.get("page_index") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid gallery image identity") from exc
        if work_id <= 0 or page_index < 0:
            raise ValueError("invalid gallery image identity")
        return f"gallery:{gallery_id}:{work_id}:p{page_index}"
    raise ValueError("director source kind must be generated or gallery")


def normalize_director_sources(raw_sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    rows = list(raw_sources or [])
    if not rows:
        raise ValueError("director source list is empty")
    if len(rows) > MAX_SOURCES:
        raise ValueError(f"single Director batch supports at most {MAX_SOURCES} sources")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("director source must be an object")
        source_id = _source_identity(raw)
        if source_id in seen:
            raise ValueError(f"duplicate director source: {source_id}")
        seen.add(source_id)
        if source_id.startswith("generated:"):
            normalized.append(
                {
                    "kind": "generated",
                    "image_id": source_id.split(":", 1)[1],
                    "source_id": source_id,
                }
            )
        else:
            _, gallery_id, work_id, page_part = source_id.split(":")
            normalized.append(
                {
                    "kind": "gallery",
                    "gallery_id": gallery_id,
                    "work_id": int(work_id),
                    "page_index": int(page_part.removeprefix("p")),
                    "source_id": source_id,
                }
            )
    return normalized


def _path_inside_data(raw: Any, *, gallery_id: str = "site", filename: str = "") -> Path | None:
    text = _text(raw, 800).replace("\\", "/")
    spec = get_spec(gallery_id)
    candidates: list[Path] = []
    if text:
        candidate = Path(text)
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            candidates.extend((data_dir() / candidate, spec.images_dir / candidate))
    if filename:
        candidates.append(spec.images_dir / Path(filename).name)
    data_root = canonical_path(data_dir())
    for candidate in candidates:
        try:
            resolved = canonical_path(candidate)
            if not path_is_within(resolved, data_root):
                continue
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            return resolved
    return None


def _gallery_asset_url(path: Path, gallery_id: str) -> str:
    """Build a browser URL from the verified file, not stale DB filenames."""

    spec = get_spec(gallery_id)
    try:
        relative = relative_to_canonical(path, spec.images_dir)
    except (OSError, ValueError):
        relative = path.name
    return f"{spec.asset_base_url}{quote(relative, safe='/')}"


def _image_dimensions(path: Path) -> tuple[int, int]:
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError("source image exceeds the 30MB Director limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                raise ValueError("source image dimensions are unsafe")
            image.verify()
    return int(width), int(height)


def resolve_director_source(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_director_sources([raw])[0]
    source_id = normalized["source_id"]
    if normalized["kind"] == "generated":
        image_id = normalized["image_id"]
        item = next((row for row in scan_all_items() if str(row.get("id") or "") == image_id), None)
        if item is None:
            raise ValueError(f"generated source was not found: {image_id}")
        path = _path_inside_data(item.get("filename"), gallery_id="site")
        if path is None:
            path = _path_inside_data(
                f"generated/{Path(str(item.get('filename') or '')).name}",
                gallery_id="site",
            )
        if path is None:
            raise ValueError(f"generated source file is missing: {image_id}")
        width, height = _image_dimensions(path)
        return {
            **normalized,
            "label": f"生成图 {image_id}",
            "image_url": str(item.get("image_url") or f"/data/generated/{path.name}"),
            "thumb_url": str(item.get("thumb_url") or f"/data/generated/{path.name}"),
            "width": width,
            "height": height,
            "path": str(path),
            "eligible": True,
        }

    gallery_id = normalized["gallery_id"]
    work_id = normalized["work_id"]
    page_index = normalized["page_index"]
    lite = get_db(gallery_id).get_work_lite(work_id)
    if not lite:
        raise ValueError(f"gallery work was not found: {gallery_id}:{work_id}")
    image = next(
        (
            row
            for row in list(lite.get("images") or [])
            if int(row.get("page_index") or 0) == page_index
        ),
        None,
    )
    if image is None:
        raise ValueError(f"gallery page was not found: {source_id}")
    filename = Path(_text(image.get("file_name"), 500)).name
    path = _path_inside_data(
        image.get("local_path"),
        gallery_id=gallery_id,
        filename=filename,
    )
    if path is None:
        raise ValueError(f"gallery page is not cached locally: {source_id}")
    width, height = _image_dimensions(path)
    work = dict(lite.get("work") or {})
    title = _text(work.get("title") or work.get("caption") or f"作品 {work_id}", 120)
    image_url = _gallery_asset_url(path, gallery_id)
    return {
        **normalized,
        "label": f"{title} · 第 {page_index + 1} 张",
        "image_url": image_url,
        "thumb_url": image_url,
        "width": width,
        "height": height,
        "path": str(path),
        "eligible": True,
    }


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in source.items() if key != "path"}


def _raw_file_fingerprint(path: Path) -> str:
    stat = path.stat()
    key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    with _SOURCE_CACHE_LOCK:
        cached = _SOURCE_RAW_HASH_CACHE.get(key)
        if cached is not None:
            _SOURCE_RAW_HASH_CACHE.move_to_end(key)
            return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    fingerprint = digest.hexdigest()
    with _SOURCE_CACHE_LOCK:
        _SOURCE_RAW_HASH_CACHE[key] = fingerprint
        _SOURCE_RAW_HASH_CACHE.move_to_end(key)
        while len(_SOURCE_RAW_HASH_CACHE) > _SOURCE_CACHE_MAX_ITEMS:
            _SOURCE_RAW_HASH_CACHE.popitem(last=False)
    return fingerprint


def _encode_preview_receipt(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_PREVIEW_SECRET, raw, hashlib.sha256).digest()
    return f"{base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def _decode_preview_receipt(preview_id: str) -> dict[str, Any]:
    try:
        payload_part, signature_part = str(preview_id or "").split(".", 1)
        raw = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4))
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        expected = hmac.new(_PREVIEW_SECRET, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("preview receipt signature mismatch")
        payload = json.loads(raw.decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("preview receipt is invalid or belongs to an earlier server session") from exc
    if not isinstance(payload, dict) or float(payload.get("expires_at") or 0) < time.time():
        raise ValueError("preview receipt has expired; run the zero-cost preview again")
    return payload


def _validate_preview_receipt(
    preview_id: str,
    sources: list[dict[str, Any]],
    recipe: dict[str, Any],
) -> list[dict[str, Any]]:
    payload = _decode_preview_receipt(preview_id)
    if payload.get("sources") != sources or payload.get("recipe") != recipe:
        raise ValueError("sources or recipe changed after preview")
    fingerprints = payload.get("fingerprints")
    if not isinstance(fingerprints, list) or len(fingerprints) != len(sources):
        raise ValueError("preview receipt does not contain a complete source snapshot")
    locked: list[dict[str, Any]] = []
    for source, expected in zip(sources, fingerprints, strict=True):
        if not isinstance(expected, dict) or expected.get("source_id") != source.get("source_id"):
            raise ValueError("preview source order changed")
        resolved = resolve_director_source(source)
        path = Path(str(resolved["path"]))
        _encoded, _width, _height, normalized = _encode_source(path)
        raw = _raw_file_fingerprint(path)
        if raw != expected.get("raw") or normalized != expected.get("normalized"):
            raise ValueError(f"source changed after preview: {source['source_id']}")
        locked.append(
            {
                **source,
                "expected_raw_fingerprint": raw,
                "expected_normalized_fingerprint": normalized,
            }
        )
    return locked


def preview_director_batch(
    sources: list[dict[str, Any]] | None,
    recipe: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_sources = normalize_director_sources(sources)
    normalized_recipe = normalize_director_recipe(recipe)
    estimated_outputs = len(normalized_sources) * int(normalized_recipe["outputs_per_source"])
    if estimated_outputs > MAX_OUTPUTS:
        raise ValueError(f"single Director batch supports at most {MAX_OUTPUTS} outputs")
    readiness = novelai_director_status()
    provider_ready = bool(readiness.get("available"))
    resolved: list[dict[str, Any]] = []
    fingerprints: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for source in normalized_sources:
        try:
            private_source = resolve_director_source(source)
            if provider_ready:
                source_path = Path(str(private_source["path"]))
                _encoded, _width, _height, normalized_fingerprint = _encode_source(source_path)
                fingerprints.append(
                    {
                        "source_id": source["source_id"],
                        "raw": _raw_file_fingerprint(source_path),
                        "normalized": normalized_fingerprint,
                    }
                )
            resolved.append(_public_source(private_source))
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            failures.append({"source_id": source["source_id"], "message": _text(exc, 300)})
    blocking_issues: list[dict[str, str]] = []
    if not provider_ready:
        blocking_issues.append(
            {
                "error": "missing_token",
                "message": "尚无可用的 NovelAI Director 槽位，请先到设置页配置或启用 NAI Token。",
            }
        )
    ready = not failures and provider_ready
    result = {
        "ok": ready,
        "ready": ready,
        "provider_ready": provider_ready,
        "provider": {
            "available": provider_ready,
            "slot_count": int(readiness.get("slot_count") or 0),
            "verified": bool(readiness.get("verified")),
            "verified_slot_count": int(readiness.get("verified_slot_count") or 0),
        },
        "blocking_issues": blocking_issues,
        "zero_provider_calls": True,
        "source_count": len(normalized_sources),
        "eligible_count": len(resolved),
        "estimated_outputs": estimated_outputs,
        "recipe": normalized_recipe,
        "sources": resolved,
        "failures": failures,
        "billing": {
            "anlas": "unknown",
            "cost_source": "upstream_not_queried",
            "message": "预检不调用 NovelAI；实际费用取决于账号与上游规则。",
        },
        "execution": {
            "concurrency": 1,
            "automatic_retry": False,
            "message": "逐张执行，失败项不会自动重扣，需在报告中手动重试。",
        },
    }
    if ready:
        result["preview_id"] = _encode_preview_receipt(
            {
                "version": 1,
                "expires_at": int(time.time()) + PREVIEW_TTL_SECONDS,
                "sources": normalized_sources,
                "recipe": normalized_recipe,
                "fingerprints": fingerprints,
            }
        )
        result["preview_expires_in"] = PREVIEW_TTL_SECONDS
    return result


def _encode_source(path: Path) -> tuple[str, int, int, str]:
    stat = path.stat()
    if stat.st_size > MAX_SOURCE_BYTES:
        raise ValueError("source image exceeds the 30MB Director limit")
    key = (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
    with _SOURCE_CACHE_LOCK:
        cached = _SOURCE_ENCODE_CACHE.get(key)
        if cached is not None:
            _SOURCE_ENCODE_CACHE.move_to_end(key)
            return cached
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                raise ValueError("source image dimensions are unsafe")
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=False)
    payload = output.getvalue()
    if len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("normalized source image exceeds the 30MB Director limit")
    result = (
        base64.b64encode(payload).decode("ascii"),
        int(width),
        int(height),
        hashlib.sha256(payload).hexdigest(),
    )
    with _SOURCE_CACHE_LOCK:
        _SOURCE_ENCODE_CACHE[key] = result
        _SOURCE_ENCODE_CACHE.move_to_end(key)
        while len(_SOURCE_ENCODE_CACHE) > _SOURCE_CACHE_MAX_ITEMS:
            _SOURCE_ENCODE_CACHE.popitem(last=False)
    return result


def _prepare_director_source(
    raw_source: dict[str, Any],
) -> tuple[dict[str, Any], str, int, int, str]:
    """Resolve, encode and verify one source using the stat-keyed caches."""
    source_id = str(raw_source["source_id"])
    resolved = resolve_director_source(raw_source)
    path = Path(str(resolved["path"]))
    image_base64, width, height, fingerprint = _encode_source(path)
    raw_fingerprint = _raw_file_fingerprint(path)
    expected_raw = _text(raw_source.get("expected_raw_fingerprint"), 80)
    expected_normalized = _text(
        raw_source.get("expected_normalized_fingerprint"),
        80,
    )
    if (
        not expected_raw
        or not expected_normalized
        or raw_fingerprint != expected_raw
        or fingerprint != expected_normalized
    ):
        raise ValueError(f"source changed after preview: {source_id}")
    return resolved, image_base64, width, height, fingerprint


async def augment_image(
    *,
    image_base64: str,
    width: int,
    height: int,
    recipe: dict[str, Any],
    source: dict[str, Any],
    token_id: str = "",
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "image": str(image_base64),
        "width": int(width),
        "height": int(height),
        "req_type": str(recipe["req_type"]),
    }
    if recipe.get("prompt"):
        request["prompt"] = str(recipe["prompt"])
    if recipe.get("defry") is not None:
        request["defry"] = int(recipe["defry"])
    public_source = _public_source(source)
    return await call_nai_director(
        request=request,
        provenance={
            "tool": recipe["tool"],
            "recipe": dict(recipe),
            "source": public_source,
            "gallery_id": source.get("gallery_id"),
            "work_id": source.get("work_id"),
        },
        token_id=token_id,
        wait_for_slot=True,
    )


def _report(status: dict[str, Any]) -> dict[str, Any]:
    items = [item for item in list(status.get("items") or []) if isinstance(item, dict)]
    raw_outputs = [
        dict(output)
        for item in items
        for output in list(item.get("outputs") or [])
        if isinstance(output, dict)
    ]
    outputs = []
    for output in raw_outputs:
        filename = Path(
            str(
                output.get("filename")
                or output.get("image_url")
                or ""
            )
        ).name
        output["available"] = bool(filename and (DIRECTOR_OUTPUT_DIR / filename).is_file())
        outputs.append(output)
    unavailable_output_count = sum(1 for output in outputs if not output["available"])
    known_costs: list[float] = []
    unknown_cost = False
    provider_attempted = False
    for item in items:
        item_attempted = bool(
            item.get("request_attempted")
            or item.get("ok")
            or item.get("billing_uncertain")
        )
        provider_attempted = provider_attempted or item_attempted
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        spent = usage.get("anlas_spent")
        if spent is None:
            if item_attempted:
                unknown_cost = True
            continue
        try:
            known_costs.append(max(0.0, float(spent)))
        except (TypeError, ValueError):
            unknown_cost = True
    blocked_retry_count = int(status.get("blocked_retry_count") or 0)
    needs_review = bool(status.get("needs_review"))
    if not items:
        anlas_spent: float | None = None
        cost_source = "not_started"
        billing_message = "任务尚未执行，没有可报告的 Anlas 记录。"
    elif unknown_cost:
        anlas_spent = None
        cost_source = "unknown"
        billing_message = "上游未返回可核验的 Anlas 消耗，请以 NovelAI 账户记录为准。"
    elif provider_attempted or known_costs:
        anlas_spent = round(sum(known_costs), 4)
        cost_source = "provider_reported"
        billing_message = "费用来自上游可核验记录。"
    else:
        anlas_spent = 0.0
        cost_source = "not_incurred"
        billing_message = "没有发起 NovelAI 请求，本任务未产生 Director 调用费用。"
    return {
        "title": "NAI 批量导演交付报告",
        "status": status.get("status"),
        "success_sources": sum(1 for item in items if item.get("ok")),
        "failed_sources": sum(1 for item in items if not item.get("ok") and not item.get("skipped")),
        "skipped_sources": sum(1 for item in items if item.get("skipped")),
        "output_count": len(outputs),
        "available_output_count": len(outputs) - unavailable_output_count,
        "unavailable_output_count": unavailable_output_count,
        "outputs": outputs,
        "failures": [
            {
                "source_id": str(item.get("source_id") or ""),
                "message": str(item.get("message") or item.get("error") or "处理失败"),
                "error": str(item.get("error") or ""),
                "retry_safe": bool(item.get("retry_safe")),
                "billing_uncertain": bool(item.get("billing_uncertain")),
            }
            for item in items
            if not item.get("ok") and not item.get("skipped")
        ],
        "anlas_spent": anlas_spent,
        "cost_source": cost_source,
        "billing_message": billing_message,
        "retryable_count": int(status.get("retryable_count") or 0),
        "blocked_retry_count": blocked_retry_count,
        "needs_review": needs_review,
        "review_message": (
            f"有 {blocked_retry_count} 个来源的上游结果或扣费状态无法确认，已禁止一键重试；请先到生成结果和 NovelAI 账户核对。"
            if needs_review and blocked_retry_count
            else ""
        ),
        "started_at": status.get("started_at") or "",
        "finished_at": status.get("finished_at") or "",
        "persistence_degraded": bool(status.get("persistence_degraded")),
        "persistence_error": str(status.get("persistence_error") or ""),
    }


def _format_director_eta(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    if rounded <= 5:
        return "即将完成"
    if rounded < 60:
        return f"约 {rounded} 秒"
    minutes, remainder = divmod(rounded, 60)
    return f"约 {minutes} 分 {remainder} 秒" if remainder else f"约 {minutes} 分钟"


def director_batch_status(task_id: str | None = None) -> dict[str, Any]:
    status = _JOB_MANAGER.status(task_id)
    if status is None:
        return {}
    job = _JOB_MANAGER.get_job(str(status.get("task_id") or ""))
    retryable, blocked = _director_retry_partition(job, status)
    status["retryable_count"] = len(retryable)
    status["blocked_retry_count"] = len(blocked)
    status["can_retry"] = bool(retryable)
    status["needs_review"] = bool(blocked) or status.get("status") == "unknown"
    status["feature"] = "nai_batch_director"
    total = int(status.get("total") or 0)
    done = int(status.get("done") or 0)
    elapsed = 0.0
    try:
        if status.get("started_at"):
            end = datetime.fromisoformat(str(status.get("finished_at") or "")) if status.get("finished_at") else datetime.now()
            elapsed = max(0.0, (end - datetime.fromisoformat(str(status["started_at"]))).total_seconds())
    except (TypeError, ValueError):
        elapsed = 0.0
    remaining = max(0, total - done)
    eta_seconds = 0.0 if status.get("terminal") else ((elapsed / done) * remaining if done > 0 else remaining * 60.0)
    phase = str(status.get("current_phase") or "")
    next_step = {
        "init": "读取并校验第一张来源图",
        "prepare_source": "核对预检指纹后提交 NovelAI",
        "director_request": "保存返回结果，再处理下一张",
    }.get(phase, "生成交付报告" if status.get("terminal") else "继续处理任务清单")
    status.update(
        {
            "elapsed_seconds": int(round(elapsed)),
            "eta_seconds": int(round(eta_seconds)),
            "eta_text": _format_director_eta(eta_seconds),
            "next_step": next_step,
        }
    )
    status["report"] = _report(status)
    return status


def director_job_revision() -> int:
    return _JOB_MANAGER.revision()


def wait_for_director_change(revision: int, timeout: float = 15.0) -> int:
    return _JOB_MANAGER.wait_for_change(revision, timeout=timeout)


def _director_retry_partition(
    job: GenerationJob | None,
    status: dict[str, Any],
) -> tuple[list[int], list[int]]:
    if job is None or not status.get("terminal"):
        return [], []
    request = job.state.get("_request")
    targets = list(request.get("targets") or []) if isinstance(request, dict) else []
    if not targets:
        return [], []
    return partition_retry_targets(
        targets,
        list(job.state.get("items") or []),
        status=str(status.get("status") or ""),
        recovered_after_restart=bool(
            status.get("recovered_after_restart")
            or job.state.get("recovered_after_restart")
        ),
        require_retry_safe=True,
    )


async def _run_director_job(
    job: GenerationJob,
    sources: list[dict[str, Any]],
    recipe: dict[str, Any],
    *,
    token_id: str,
) -> None:
    try:
        prepare_task: asyncio.Task[
            tuple[dict[str, Any], str, int, int, str]
        ] | None = (
            asyncio.create_task(asyncio.to_thread(_prepare_director_source, sources[0]))
            if sources
            else None
        )
        for target_index, raw_source in enumerate(sources):
            if job.cancel_requested:
                break
            current_prepare_task = prepare_task
            prepare_task = (
                asyncio.create_task(
                    asyncio.to_thread(
                        _prepare_director_source,
                        sources[target_index + 1],
                    )
                )
                if target_index + 1 < len(sources)
                else None
            )
            source_id = raw_source["source_id"]
            _JOB_MANAGER.update(
                job,
                current_phase="prepare_source",
                current_source_id=source_id,
                message=f"正在读取第 {target_index + 1}/{len(sources)} 张来源图",
            )
            provider_stage_started = False
            try:
                if current_prepare_task is None:
                    raise RuntimeError("Director source preparation was not scheduled")
                (
                    resolved,
                    image_base64,
                    width,
                    height,
                    fingerprint,
                ) = await current_prepare_task
                _JOB_MANAGER.update(
                    job,
                    current_phase="director_request",
                    current_source_id=source_id,
                    message=(
                        f"正在执行第 {target_index + 1}/{len(sources)} 张 · "
                        "当前请求返回前不会启动下一张"
                    ),
                )
                provider_stage_started = True
                result = await augment_image(
                    image_base64=image_base64,
                    width=width,
                    height=height,
                    recipe=recipe,
                    source={**resolved, "source_fingerprint": fingerprint},
                    token_id=token_id,
                )
                item = {
                    "target_index": target_index,
                    "source": _public_source(resolved),
                    "source_id": source_id,
                    "ok": bool(result.get("ok")),
                    "outputs": list(result.get("outputs") or []),
                    "usage": dict(result.get("usage") or {}),
                    "message": _text(result.get("message"), 500),
                    "error": _text(result.get("error"), 80),
                    "retry_safe": bool(result.get("retry_safe")) if not result.get("ok") else False,
                    "billing_uncertain": bool(result.get("billing_uncertain")),
                    "request_attempted": bool(
                        result.get("request_attempted", provider_stage_started)
                    ),
                }
                if item["ok"]:
                    _JOB_MANAGER.increment(job, "ok_count")
                else:
                    _JOB_MANAGER.increment(job, "fail_count")
                _JOB_MANAGER.append_item(job, item, count_done=True)
            except Exception as exc:
                _JOB_MANAGER.increment(job, "fail_count")
                _JOB_MANAGER.append_item(
                    job,
                    {
                        "target_index": target_index,
                        "source_id": source_id,
                        "ok": False,
                        "outputs": [],
                        "message": _text(exc, 500),
                        "error": "source_or_request_failed",
                        "retry_safe": not provider_stage_started,
                        "billing_uncertain": provider_stage_started,
                        "request_attempted": provider_stage_started,
                    },
                    count_done=True,
                )
            if job.cancel_requested:
                break

        if prepare_task is not None:
            if not prepare_task.done():
                prepare_task.cancel()
            await asyncio.gather(prepare_task, return_exceptions=True)

        if job.cancel_requested:
            _JOB_MANAGER.finish(
                job,
                status="cancelled",
                message="已在当前上游请求安全返回后停止，未开始剩余图片",
                current_source_id="",
            )
            return
        status = _JOB_MANAGER.status(job.task_id) or {}
        ok_count = int(status.get("ok_count") or 0)
        fail_count = int(status.get("fail_count") or 0)
        output_count = sum(len(item.get("outputs") or []) for item in status.get("items") or [])
        terminal_status = "error" if fail_count > 0 and ok_count == 0 else "done"
        message = (
            f"批量导演失败：{fail_count} 个来源均未成功；请查看失败原因和重试安全提示"
            if terminal_status == "error"
            else f"批量导演处理结束：成功 {ok_count}，失败 {fail_count}，交付 {output_count} 张结果"
        )
        _JOB_MANAGER.finish(job, status=terminal_status, message=message, current_source_id="")
    except asyncio.CancelledError:
        current = _JOB_MANAGER.status(job.task_id) or {}
        if current.get("status") == "running":
            _JOB_MANAGER.finish(
                job,
                status="unknown",
                message="任务进程被中断；为避免重复扣费，未自动重试，请先核对生成结果",
            )
    except Exception as exc:
        current = _JOB_MANAGER.status(job.task_id) or {}
        if current.get("status") == "running":
            _JOB_MANAGER.finish(job, status="error", message=_text(exc, 500))


def start_director_batch(
    sources: list[dict[str, Any]] | None,
    recipe: dict[str, Any] | None,
    *,
    confirmed: bool,
    preview_id: str = "",
    token_id: str = "",
    _retry_of: str = "",
) -> dict[str, Any]:
    global _TASK
    if confirmed is not True:
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "请先完成零费用预检，再明确确认可能产生 Anlas 消耗的批量导演任务",
        }
    try:
        normalized_sources = normalize_director_sources(sources)
        normalized_recipe = normalize_director_recipe(recipe)
        if not _text(preview_id, 20000):
            return {
                "ok": False,
                "error": "preview_required",
                "message": "请先完成零费用预检，再使用服务器签发的预检凭证确认执行",
            }
        locked_sources = _validate_preview_receipt(
            preview_id,
            normalized_sources,
            normalized_recipe,
        )
    except ValueError as exc:
        return {"ok": False, "error": "stale_preview", "message": str(exc)}
    readiness = novelai_director_status()
    if not readiness.get("available"):
        return {
            "ok": False,
            "error": "missing_token",
            "message": "尚无可用的 NovelAI Director 槽位，请先到设置页配置或启用 NAI Token",
        }
    try:
        job = _JOB_MANAGER.start_job(
            total=len(normalized_sources),
            generate=True,
            preview_only=False,
        )
    except JobAlreadyRunning as exc:
        return {
            "ok": False,
            "error": "busy",
            "message": "已有批量导演任务正在执行",
            "task_id": exc.status.get("task_id"),
            "batch": exc.status,
        }
    except JobPersistenceError as exc:
        return {
            "ok": False,
            "error": "persistence_unavailable",
            "message": f"任务状态无法安全保存，未调用 NovelAI：{exc}",
        }
    _JOB_MANAGER.update(
        job,
        _request={
            "targets": copy.deepcopy(locked_sources),
            "recipe": copy.deepcopy(normalized_recipe),
            "token_id": _text(token_id, 100),
        },
        recipe=copy.deepcopy(normalized_recipe),
        planned_outputs=len(locked_sources) * int(normalized_recipe["outputs_per_source"]),
        retry_of=_text(_retry_of, 64),
        current_source_id="",
        message="任务已接收，正在准备第一张来源图",
    )
    coroutine = _run_director_job(
        job,
        locked_sources,
        normalized_recipe,
        token_id=_text(token_id, 100),
    )
    try:
        task = asyncio.create_task(coroutine)
    except Exception as exc:
        coroutine.close()
        _JOB_MANAGER.finish(job, status="error", message=_text(exc, 500))
        return {
            "ok": False,
            "error": "start_failed",
            "message": str(exc),
            "task_id": job.task_id,
            "batch": director_batch_status(job.task_id),
        }
    _JOB_MANAGER.attach_task(job, task)
    _TASK = task
    return {
        "ok": True,
        "message": "批量导演任务已开始",
        "task_id": job.task_id,
        "retry_of": _text(_retry_of, 64),
        "batch": director_batch_status(job.task_id),
    }


def cancel_director_batch(task_id: str | None = None) -> dict[str, Any]:
    if task_id and _JOB_MANAGER.status(task_id) is None:
        return {
            "ok": False,
            "error": "not_found",
            "task_id": task_id,
            "message": "批量导演任务不存在",
        }
    job = _JOB_MANAGER.request_cancel(task_id)
    if job is None:
        return {"ok": True, "message": "当前没有运行中的批量导演任务", "batch": director_batch_status()}
    status = director_batch_status(job.task_id)
    return {
        "ok": True,
        "task_id": job.task_id,
        "message": (
            "已请求停止；如果当前图片已提交给上游，会先保存返回结果再停止"
            if status.get("status") == "running"
            else "任务已经结束"
        ),
        "batch": status,
    }


def _retry_director_request(task_id: str) -> tuple[GenerationJob | None, dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    previous = _JOB_MANAGER.get_job(_text(task_id, 64))
    if previous is None:
        return None, {}, [], {}, {"ok": False, "error": "not_found", "message": "批量导演任务不存在"}
    status = director_batch_status(previous.task_id)
    if not status.get("terminal"):
        return previous, status, [], {}, {"ok": False, "error": "not_terminal", "message": "运行中的任务不能重试"}
    request = copy.deepcopy(previous.state.get("_request"))
    if not isinstance(request, dict) or not isinstance(request.get("targets"), list):
        return previous, status, [], {}, {"ok": False, "error": "retry_unavailable", "message": "历史任务没有可重试清单"}
    retryable, blocked = _director_retry_partition(previous, status)
    if not retryable and blocked:
        return previous, status, [], request, {
            "ok": False,
            "error": "needs_review",
            "message": "存在结果或扣费状态无法确认的来源，已禁止盲目重试；请先核对生成结果和 NovelAI 账户",
            "blocked_retry_count": len(blocked),
        }
    retryable_set = set(retryable)
    retry_sources = [
        copy.deepcopy(source)
        for index, source in enumerate(request["targets"])
        if index in retryable_set
    ]
    if not retry_sources:
        return previous, status, [], request, {"ok": False, "error": "nothing_to_retry", "message": "没有失败或未完成的图片"}
    return previous, status, retry_sources, request, None


def preview_director_retry(task_id: str) -> dict[str, Any]:
    previous, _status, retry_sources, request, error = _retry_director_request(task_id)
    if error:
        return error
    preview = preview_director_batch(retry_sources, dict(request.get("recipe") or {}))
    preview["retry_of"] = previous.task_id if previous else ""
    preview["retry_source_count"] = len(retry_sources)
    return preview


def retry_director_batch(
    task_id: str,
    *,
    confirmed: bool = False,
    preview_id: str = "",
) -> dict[str, Any]:
    previous, _status, retry_sources, request, error = _retry_director_request(task_id)
    if error:
        return error
    if confirmed is not True:
        return {
            "ok": False,
            "error": "confirmation_required",
            "message": "请先预检失败项，并再次确认可能产生 Anlas 消耗的重试",
        }
    return start_director_batch(
        retry_sources,
        dict(request.get("recipe") or {}),
        confirmed=True,
        preview_id=preview_id,
        token_id=_text(request.get("token_id"), 100),
        _retry_of=previous.task_id if previous else "",
    )


def list_director_sources(
    *,
    kind: str = "generated",
    mode: str = "single",
    q: str = "",
    gallery_id: str = "site",
    page: int = 1,
    page_size: int = 24,
) -> dict[str, Any]:
    source_kind = _text(kind, 20).lower()
    selection_mode = _text(mode, 20).lower() or "single"
    query = _text(q, 200).lower()
    limit = max(1, min(int(page_size), 60))
    page_number = max(1, int(page))
    if source_kind == "generated":
        if selection_mode not in {"series", "single"}:
            raise ValueError("generated source mode must be series or single")
        if selection_mode == "series":
            summaries = []
            for summary in list_groups():
                haystack = " ".join(
                    str(summary.get(key) or "")
                    for key in ("group_id", "work_id", "source_gallery_id", "cover_id")
                ).lower()
                if query and query not in haystack:
                    continue
                summaries.append(summary)
            start = (page_number - 1) * limit
            rows: list[dict[str, Any]] = []
            for summary in summaries[start : start + limit]:
                group_id = _text(summary.get("group_id"), 200)
                count = max(0, int(summary.get("count") or 0))
                if not group_id or count <= 0:
                    continue
                work_id = summary.get("work_id")
                gallery = _text(summary.get("source_gallery_id") or "site", 30)
                title = f"作品 {work_id}" if work_id else "独立生成"
                if gallery != "site" and work_id:
                    title = f"{gallery} · {title}"
                rows.append(
                    {
                        "source_id": f"generated-group:{group_id}",
                        "kind": "generated_group",
                        "group_id": group_id,
                        "label": title,
                        "count": count,
                        "image_url": summary.get("cover_url") or "",
                        "thumb_url": summary.get("cover_thumb") or summary.get("cover_url") or "",
                        "created_at": summary.get("latest_at") or "",
                        "eligible": count <= MAX_SOURCES,
                        "details_loaded": False,
                    }
                )
            return {
                "ok": True,
                "kind": source_kind,
                "mode": selection_mode,
                "page": page_number,
                "page_size": limit,
                "total": len(summaries),
                "items": rows,
            }
        rows = []
        for item in scan_all_items():
            haystack = " ".join(
                str(item.get(key) or "")
                for key in ("id", "model", "source_gallery_id", "work_id")
            ).lower()
            if query and query not in haystack:
                continue
            rows.append(
                {
                    "source_id": f"generated:{item['id']}",
                    "kind": "generated",
                    "image_id": item["id"],
                    "group_id": "",
                    "label": f"生成图 {item['id']}",
                    "image_url": item.get("image_url") or "",
                    "thumb_url": item.get("thumb_url") or item.get("image_url") or "",
                    "created_at": item.get("created_at") or "",
                    "eligible": True,
                }
            )
        start = (page_number - 1) * limit
        return {
            "ok": True,
            "kind": source_kind,
            "mode": selection_mode,
            "page": page_number,
            "page_size": limit,
            "total": len(rows),
            "items": rows[start : start + limit],
        }
    if source_kind != "gallery":
        raise ValueError("source catalog kind must be generated or gallery")

    gallery = normalize_gallery_id(gallery_id)
    db = get_db(gallery)
    result = db.list_local_image_sources(
        q=_text(q, 200),
        page=page_number,
        page_size=limit,
        local_scope=get_spec(gallery).local_scope,
        nai_only=True,
    )
    items: list[dict[str, Any]] = []
    for image in result.get("items") or []:
        work_id = int(image.get("work_id") or 0)
        title = _text(image.get("title") or image.get("caption") or f"作品 {work_id}", 120)
        page_index = int(image.get("page_index") or 0)
        filename = Path(_text(image.get("file_name"), 500)).name
        path = _path_inside_data(
            image.get("local_path"),
            gallery_id=gallery,
            filename=filename,
        )
        if path is None:
            continue
        items.append(
            {
                "source_id": f"gallery:{gallery}:{work_id}:p{page_index}",
                "kind": "gallery",
                "gallery_id": gallery,
                "work_id": work_id,
                "page_index": page_index,
                "label": f"{title} · 第 {page_index + 1} 张",
                "image_url": _gallery_asset_url(path, gallery),
                "thumb_url": _gallery_asset_url(path, gallery),
                "eligible": True,
            }
        )
    return {
        "ok": True,
        "kind": source_kind,
        "mode": "single",
        "gallery_id": gallery,
        "page": page_number,
        "page_size": limit,
        "total": int(result.get("total") or len(items)),
        "items": items,
    }


def get_director_source_group(group_id: str) -> dict[str, Any]:
    """Expand one generated series only after the user selects it."""
    safe_group_id = _text(group_id, 200)
    if not safe_group_id:
        raise ValueError("generated group id is required")
    group = get_group(safe_group_id, rescan_if_missing=False)
    if not group:
        raise ValueError("generated group does not exist")
    images: list[dict[str, Any]] = []
    for item in group.get("items") or []:
        image_id = _text(item.get("id"), 100)
        if not image_id:
            continue
        images.append(
            {
                "source_id": f"generated:{image_id}",
                "kind": "generated",
                "image_id": image_id,
                "group_id": safe_group_id,
                "label": f"生成图 {image_id}",
                "image_url": item.get("image_url") or "",
                "thumb_url": item.get("thumb_url") or item.get("image_url") or "",
                "created_at": item.get("created_at") or "",
                "eligible": True,
            }
        )
    if not images:
        raise ValueError("generated group has no usable images")
    work_id = group.get("work_id")
    gallery = _text(group.get("source_gallery_id") or "site", 30)
    title = f"作品 {work_id}" if work_id else "独立生成"
    if gallery != "site" and work_id:
        title = f"{gallery} · {title}"
    return {
        "ok": True,
        "source": {
            "source_id": f"generated-group:{safe_group_id}",
            "kind": "generated_group",
            "group_id": safe_group_id,
            "label": title,
            "count": len(images),
            "items": images,
            "image_url": group.get("cover_url") or images[0]["image_url"],
            "thumb_url": group.get("cover_thumb") or images[0]["thumb_url"],
            "created_at": group.get("latest_at") or "",
            "eligible": len(images) <= MAX_SOURCES,
            "details_loaded": True,
        },
    }

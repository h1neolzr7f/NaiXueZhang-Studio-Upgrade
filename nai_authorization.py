"""Server-side one-time tickets for non-free NovelAI generation.

Frontend confirmation is not a security boundary. After compile, any request
that is not free_eligible must present a ticket bound to the frozen manifest,
action, copies, and cost-relevant payload hash. Replay, expiry, and hash
mismatch are rejected before NovelAI HTTP transport.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any

from nai_char_modules.generation import build_generate_payload

TICKET_TTL_SECONDS = 600
TICKET_VERSION = 1
ACTION_STUDIO = "studio_generate"
ACTION_CHAR_SWAP = "char_swap_batch"
ACTION_BUTLER = "butler_generate"
MAX_TICKET_COPIES = {
    ACTION_STUDIO: 8,
    ACTION_BUTLER: 8,
    ACTION_CHAR_SWAP: 250,
}

_SECRET = secrets.token_bytes(32)
_CONSUMED: dict[str, float] = {}
_LOCK = threading.Lock()


class AuthorizationError(ValueError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def reset_authorization_state_for_tests() -> None:
    with _LOCK:
        _CONSUMED.clear()


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _blob_fingerprint(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    elif isinstance(value, list):
        return ",".join(_blob_fingerprint(item) for item in value)
    else:
        raw = str(value).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()


def cost_relevant_view(compiled: dict[str, Any], *, copies: int, action: str) -> dict[str, Any]:
    parameters = compiled.get("parameters") if isinstance(compiled.get("parameters"), dict) else {}
    return {
        "action": str(compiled.get("action") or ""),
        "requested_action": str(compiled.get("requested_action") or action),
        "copies": int(copies),
        "model": str(compiled.get("model") or ""),
        "width": int(compiled.get("width") or 0),
        "height": int(compiled.get("height") or 0),
        "steps": int(compiled.get("steps") or 0),
        "sm": bool(parameters.get("sm")),
        "sm_dyn": bool(parameters.get("sm_dyn")),
        "autoSmea": bool(parameters.get("autoSmea")),
        "smea": bool(parameters.get("smea")),
        "has_image": bool(parameters.get("image") or compiled.get("action") in {"img2img", "infill"}),
        "has_mask": bool(parameters.get("mask")),
        "has_reference": bool(parameters.get("reference_image_multiple")),
        "free_eligible": bool(compiled.get("free_eligible")),
    }


def comment_manifest_view(comment: dict[str, Any] | None) -> dict[str, Any]:
    source = comment if isinstance(comment, dict) else {}
    return {
        "width": source.get("width"),
        "height": source.get("height"),
        "steps": source.get("steps"),
        "sm": bool(source.get("sm")),
        "sm_dyn": bool(source.get("sm_dyn")),
        "autoSmea": bool(source.get("autoSmea")),
        "smea": bool(source.get("smea")),
        "action": source.get("action") or source.get("request_type"),
        "model": source.get("model"),
        "Source": source.get("Source"),
        "image": _blob_fingerprint(source.get("image")),
        "mask": _blob_fingerprint(source.get("mask")),
        "reference_image_multiple": _blob_fingerprint(source.get("reference_image_multiple")),
        "prompt": str(source.get("prompt") or ""),
        "uc": str(source.get("uc") or source.get("negative_prompt") or ""),
    }


def payload_hash(views: list[dict[str, Any]]) -> str:
    return hashlib.sha256(_canonical(views)).hexdigest()


def target_fingerprint(item: dict[str, Any] | None) -> str:
    source = item if isinstance(item, dict) else {}
    return hashlib.sha256(
        _canonical(
            {
                "work_id": source.get("work_id"),
                "page_index": source.get("page_index"),
                "gallery_id": source.get("gallery_id"),
                "comment": comment_manifest_view(source.get("patched_comment")),
            }
        )
    ).hexdigest()


def target_fingerprints(targets: list[dict[str, Any]] | None) -> list[str]:
    return [target_fingerprint(item) for item in (targets or [])]


def manifest_hash(
    targets: list[dict[str, Any]],
    recipe: dict[str, Any] | None,
    *,
    copies: int,
    action: str,
) -> str:
    body = {
        "action": action,
        "copies": int(copies),
        "recipe": recipe or {},
        "targets": [
            {
                "work_id": item.get("work_id"),
                "page_index": item.get("page_index"),
                "gallery_id": item.get("gallery_id"),
                "comment": comment_manifest_view(item.get("patched_comment")),
            }
            for item in targets
        ],
    }
    return hashlib.sha256(_canonical(body)).hexdigest()


def compile_batch_authorization(
    targets: list[dict[str, Any]],
    recipe: dict[str, Any] | None = None,
    *,
    force_free: bool = True,
    action: str = ACTION_CHAR_SWAP,
    copies: int | None = None,
) -> dict[str, Any]:
    recipe = recipe if isinstance(recipe, dict) else {}
    rows = list(targets or [])
    copy_count = int(copies if copies is not None else (recipe.get("copies") or len(rows) or 1))
    compiled_rows: list[dict[str, Any]] = []
    views: list[dict[str, Any]] = []
    unknown = True
    all_free = True
    for item in rows:
        comment = item.get("patched_comment")
        if not isinstance(comment, dict) or not comment:
            continue
        compiled = build_generate_payload(comment, force_free=bool(force_free))
        unknown = False
        if not compiled.get("free_eligible"):
            all_free = False
        compiled_rows.append(
            {
                "action": compiled.get("action"),
                "free_eligible": bool(compiled.get("free_eligible")),
                "width": compiled.get("width"),
                "height": compiled.get("height"),
                "steps": compiled.get("steps"),
                "model": compiled.get("model"),
            }
        )
        views.append(cost_relevant_view(compiled, copies=copy_count, action=action))
    if unknown:
        all_free = bool(force_free)
        views.append(
            {
                "action": action,
                "copies": copy_count,
                "force_free": bool(force_free),
                "target_ids": [item.get("work_id") for item in rows],
                "unknown_eligibility": True,
            }
        )
        if not force_free:
            all_free = False
    requires_ticket = (not unknown and not all_free) or (unknown and not force_free)
    return {
        "ok": True,
        "action": action,
        "copies": copy_count,
        "force_free": bool(force_free),
        "free_eligible": bool(all_free and not unknown),
        "unknown_eligibility": unknown,
        "requires_ticket": requires_ticket,
        "compiled": compiled_rows,
        "payload_hash": payload_hash(views),
        "manifest_hash": manifest_hash(rows, recipe, copies=copy_count, action=action),
    }


def _encode(payload: dict[str, Any]) -> str:
    raw = _canonical(payload)
    signature = hmac.new(_SECRET, raw, hashlib.sha256).digest()
    return (
        f"{base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')}."
        f"{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"
    )


def _decode(ticket: str) -> dict[str, Any]:
    try:
        payload_part, signature_part = str(ticket or "").split(".", 1)
        raw = base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4))
        signature = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        expected = hmac.new(_SECRET, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise AuthorizationError("authorization ticket signature mismatch", error_code="ticket_invalid")
        payload = json.loads(raw.decode("utf-8"))
    except AuthorizationError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthorizationError("authorization ticket is invalid", error_code="ticket_invalid") from exc
    if not isinstance(payload, dict):
        raise AuthorizationError("authorization ticket is invalid", error_code="ticket_invalid")
    if float(payload.get("expires_at") or 0) < time.time():
        raise AuthorizationError("authorization ticket has expired", error_code="ticket_expired")
    return payload


def max_ticket_copies(action: str) -> int:
    return int(MAX_TICKET_COPIES.get(str(action or ""), 8))


def authorization_seal(
    preview: dict[str, Any],
    fingerprints: list[str] | None = None,
) -> str:
    body = {
        "action": preview.get("action"),
        "copies": int(preview.get("copies") or 0),
        "force_free": bool(preview.get("force_free", True)),
        "payload_hash": preview.get("payload_hash"),
        "manifest_hash": preview.get("manifest_hash"),
        "target_fingerprints": list(fingerprints if fingerprints is not None else preview.get("target_fingerprints") or []),
    }
    return hmac.new(_SECRET, _canonical(body), hashlib.sha256).hexdigest()


def verify_authorization_seal(stored: dict[str, Any]) -> None:
    expected = authorization_seal(
        {
            "action": stored.get("action") or stored.get("authorization_action"),
            "copies": stored.get("copies"),
            "force_free": stored.get("force_free", True),
            "payload_hash": stored.get("payload_hash"),
            "manifest_hash": stored.get("manifest_hash"),
        },
        list(stored.get("target_fingerprints") or []),
    )
    got = str(stored.get("authorization_seal") or "")
    if not got or not hmac.compare_digest(expected, got):
        raise AuthorizationError(
            "retry authorization seal mismatch",
            error_code="ticket_hash_mismatch",
        )


def issue_ticket(preview: dict[str, Any], *, ttl_seconds: int = TICKET_TTL_SECONDS) -> str:
    nonce = secrets.token_urlsafe(16)
    payload = {
        "v": TICKET_VERSION,
        "nonce": nonce,
        "action": preview["action"],
        "copies": int(preview["copies"]),
        "force_free": bool(preview.get("force_free", True)),
        "payload_hash": preview["payload_hash"],
        "manifest_hash": preview["manifest_hash"],
        "expires_at": time.time() + max(30, int(ttl_seconds)),
    }
    return _encode(payload)


def _matches(payload: dict[str, Any], preview: dict[str, Any]) -> None:
    if payload.get("action") != preview.get("action"):
        raise AuthorizationError("authorization action changed", error_code="ticket_hash_mismatch")
    if int(payload.get("copies") or 0) != int(preview.get("copies") or 0):
        raise AuthorizationError("authorization copies changed", error_code="ticket_hash_mismatch")
    if payload.get("payload_hash") != preview.get("payload_hash"):
        raise AuthorizationError("authorization payload hash mismatch", error_code="ticket_hash_mismatch")
    if payload.get("manifest_hash") != preview.get("manifest_hash"):
        raise AuthorizationError("authorization manifest hash mismatch", error_code="ticket_hash_mismatch")


def validate_ticket(ticket: str, preview: dict[str, Any]) -> dict[str, Any]:
    payload = _decode(ticket)
    _matches(payload, preview)
    nonce = str(payload.get("nonce") or "")
    with _LOCK:
        if nonce in _CONSUMED:
            raise AuthorizationError("authorization ticket already used", error_code="ticket_replay")
    return payload


def consume_ticket(ticket: str, preview: dict[str, Any]) -> dict[str, Any]:
    payload = validate_ticket(ticket, preview)
    nonce = str(payload.get("nonce") or "")
    with _LOCK:
        if nonce in _CONSUMED:
            raise AuthorizationError("authorization ticket already used", error_code="ticket_replay")
        _CONSUMED[nonce] = time.time()
        cutoff = time.time() - TICKET_TTL_SECONDS - 60
        for key, used_at in list(_CONSUMED.items()):
            if used_at < cutoff:
                _CONSUMED.pop(key, None)
    return payload


def authorize_start_batch(
    targets: list[dict[str, Any]],
    recipe: dict[str, Any] | None,
    *,
    force_free: bool,
    generate: bool,
    preview_only: bool,
    action: str,
    ticket: str = "",
    paid_authorized: bool = False,
    retry_of: str = "",
    stored_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    preview = compile_batch_authorization(
        targets,
        recipe,
        force_free=force_free,
        action=action,
    )
    fingerprints = target_fingerprints(targets)
    preview["target_fingerprints"] = fingerprints
    preview["authorization_seal"] = authorization_seal(preview, fingerprints)
    if not generate or preview_only:
        preview["authorized"] = True
        preview["paid_authorized"] = False
        return preview
    if not preview["requires_ticket"]:
        preview["authorized"] = True
        preview["paid_authorized"] = False
        return preview
    if paid_authorized and retry_of and stored_hashes:
        verify_authorization_seal(stored_hashes)
        frozen_fps = {str(item) for item in (stored_hashes.get("target_fingerprints") or []) if item}
        current_fps = set(fingerprints)
        if frozen_fps and current_fps and current_fps.issubset(frozen_fps):
            preview["authorized"] = True
            preview["paid_authorized"] = True
            preview["retry_reused"] = True
            return preview
        if (
            stored_hashes.get("payload_hash") == preview["payload_hash"]
            and stored_hashes.get("manifest_hash") == preview["manifest_hash"]
        ):
            preview["authorized"] = True
            preview["paid_authorized"] = True
            preview["retry_reused"] = True
            return preview
        raise AuthorizationError(
            "retry authorization hashes do not match the frozen job",
            error_code="ticket_hash_mismatch",
        )
    consume_ticket(str(ticket or ""), preview)
    preview["authorized"] = True
    preview["paid_authorized"] = True
    return preview


def issue_for_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Internal issue after a confirmed Butler/workflow action."""

    issued = dict(preview)
    if issued.get("requires_ticket"):
        issued["ticket"] = issue_ticket(issued)
    else:
        issued["ticket"] = ""
    return issued


def issue_http_preview(preview: dict[str, Any], *, confirmed: bool = False) -> dict[str, Any]:
    """HTTP authorize: tickets are issued only after an explicit confirmation.

    This is a local trust model. The ticket is an HMAC bound to the frozen
    cost view; it is not a remote billing receipt. Copies are capped per action.
    """

    issued = dict(preview)
    cap = max_ticket_copies(str(issued.get("action") or ""))
    copies = int(issued.get("copies") or 1)
    issued["local_trust"] = True
    issued["max_copies"] = cap
    issued["needs_confirmation"] = bool(issued.get("requires_ticket") and not confirmed)
    if copies > cap:
        issued["ok"] = False
        issued["error"] = "quantity_limit"
        issued["ticket"] = ""
        issued["message"] = f"copies exceed local authorization cap {cap}"
        return issued
    if issued.get("requires_ticket") and confirmed:
        issued["ticket"] = issue_ticket(issued)
    else:
        issued["ticket"] = ""
    return issued

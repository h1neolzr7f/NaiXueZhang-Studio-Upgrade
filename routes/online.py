from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from capability.gateway import CapabilityGateway
from capability.orchestrator import Orchestrator
from online_library import add_to_my_library, favorite_remote, list_favorites, search_online

router = APIRouter(prefix="/api")
_GATEWAY = CapabilityGateway()
_ORCH = Orchestrator(_GATEWAY)


@router.get("/online/search")
def api_online_search(q: str = Query(""), limit: int = Query(24, ge=1, le=80)) -> dict:
    return search_online(q, limit=limit)


@router.post("/online/favorite")
def api_online_favorite(payload: dict = Body(default_factory=dict)) -> dict:
    remote_id = str(payload.get("remote_id") or "").strip()
    if not remote_id:
        raise HTTPException(status_code=400, detail="remote_id is required")
    try:
        return favorite_remote(remote_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="remote asset not found") from exc


@router.get("/online/favorites")
def api_online_favorites() -> dict:
    return {"ok": True, "section": "online", "items": list_favorites()}


@router.post("/online/add-to-library")
def api_online_add_to_library(payload: dict = Body(default_factory=dict)) -> dict:
    remote_id = str(payload.get("remote_id") or "").strip()
    gallery_id = str(payload.get("gallery_id") or "codex").strip() or "codex"
    if not remote_id:
        raise HTTPException(status_code=400, detail="remote_id is required")
    try:
        return add_to_my_library(remote_id, gallery_id=gallery_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="remote asset not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/capability/decide")
def api_capability_decide(payload: dict = Body(default_factory=dict)) -> dict:
    decision = _GATEWAY.decide(
        str(payload.get("persona_id") or "service"),
        str(payload.get("capability_id") or ""),
        confirmed=bool(payload.get("confirmed")),
        delegation_token=str(payload.get("delegation_token") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        provider_scope=str(payload.get("provider_scope") or ""),
        asset_scope=str(payload.get("asset_scope") or ""),
        payload_hash=str(payload.get("payload_hash") or ""),
        quantity=int(payload.get("quantity") or 1),
    )
    return {
        "ok": decision.decision != "DENY",
        "decision": decision.decision,
        "reason": decision.reason,
        "capability_id": decision.capability_id,
        "persona_id": decision.persona_id,
        "workflow_request": decision.workflow_request,
    }


@router.post("/capability/route")
def api_capability_route(payload: dict = Body(default_factory=dict)) -> dict:
    return _ORCH.route(
        str(payload.get("user_intent") or ""),
        from_persona=str(payload.get("from_persona") or "service"),
    )

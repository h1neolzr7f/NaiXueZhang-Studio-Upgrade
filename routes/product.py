from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from product_ops import PRODUCT_STRATEGY, build_product_health, build_verification_plan
from server_shared import CONFIG, ROOT, WEB_DIR

router = APIRouter(prefix="/api/product")
page_router = APIRouter()


@router.get("/strategy")
def api_product_strategy() -> dict:
    return {"ok": True, "strategy": PRODUCT_STRATEGY}


@router.get("/health")
def api_product_health() -> dict:
    health = build_product_health(CONFIG, ROOT)
    health.pop("paths", None)
    return {"ok": True, "health": health}


@router.get("/verification")
def api_product_verification() -> dict:
    return {"ok": True, "verification": build_verification_plan()}


@page_router.get("/ops")
def ops_page() -> FileResponse:
    return FileResponse(
        Path(WEB_DIR) / "ops.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@page_router.get("/tag-assets")
def tag_assets_page() -> FileResponse:
    return FileResponse(
        Path(WEB_DIR) / "tag-assets.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@page_router.get("/aitag-library")
def aitag_library_page() -> FileResponse:
    """Dedicated online AITag library; UI logic is shared with the asset workbench."""

    return FileResponse(
        Path(WEB_DIR) / "tag-assets.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@page_router.get("/pipeline")
def pipeline_page() -> FileResponse:
    return FileResponse(
        Path(WEB_DIR) / "pipeline.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@page_router.get("/references")
def references_page() -> FileResponse:
    return FileResponse(
        Path(WEB_DIR) / "references.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

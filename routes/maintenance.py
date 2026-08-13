"""Local-only maintenance Interface for Gallery assets and snapshots."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from gallery_maintenance import GalleryMaintenance
from gallery_snapshot import maintenance_mode_active


def build_router(data_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api/maintenance", tags=["gallery-maintenance"])
    maintenance = GalleryMaintenance(Path(data_dir))

    def _reject_during_restore() -> None:
        # A snapshot restore swaps the DB and images tree; maintenance writes
        # must refuse while the lock file is present.
        if maintenance_mode_active(Path(data_dir)):
            raise HTTPException(
                status_code=409,
                detail="gallery maintenance (snapshot restore) is in progress",
            )

    @router.get("/storage")
    def storage_status() -> dict:
        return {"ok": True, "storage": maintenance.storage_status()}

    @router.post("/thumbnails/rebuild")
    def rebuild_thumbnails() -> dict:
        _reject_during_restore()
        return {"ok": True, "receipt": maintenance.rebuild_thumbnails()}

    @router.post("/nai-tags/rebuild")
    def rebuild_nai_tags() -> dict:
        _reject_during_restore()
        return {"ok": True, "receipt": maintenance.rebuild_nai_tag_index()}

    @router.post("/orphans/preview")
    def preview_orphans() -> dict:
        return {"ok": True, "receipt": maintenance.reconcile(delete=False)}

    @router.post("/orphans/clean")
    def clean_orphans(payload: dict = Body(default_factory=dict)) -> dict:
        _reject_during_restore()
        if payload.get("confirm") is not True:
            raise HTTPException(status_code=400, detail="cleanup requires confirm=true")
        return {"ok": True, "receipt": maintenance.reconcile(delete=True)}

    @router.get("/skips/permanent")
    def permanent_skips() -> dict:
        """List works permanently skipped because no NAI data was collected."""

        return {"ok": True, "receipt": maintenance.permanent_skip_report()}

    @router.post("/staging/cleanup")
    def cleanup_staging(payload: dict = Body(default_factory=dict)) -> dict:
        """Preview or delete leftover crawler staging files (no gallery data)."""

        _reject_during_restore()
        delete = payload.get("confirm") is True
        return {
            "ok": True,
            "receipt": maintenance.cleanup_stale_staging(delete=delete),
        }

    @router.post("/originals/migrate-webp")
    def migrate_originals_webp(payload: dict = Body(default_factory=dict)) -> dict:
        """Compress existing PNG/JPEG gallery originals into WebP."""

        _reject_during_restore()
        dry_run = payload.get("confirm") is not True
        raw_limit = payload.get("limit")
        if raw_limit in (None, ""):
            limit = 0
        elif isinstance(raw_limit, bool):
            raise HTTPException(
                status_code=422, detail="limit must be a non-negative integer"
            )
        elif isinstance(raw_limit, int):
            limit = raw_limit
        elif isinstance(raw_limit, str) and raw_limit.strip().isdigit():
            limit = int(raw_limit.strip())
        else:
            raise HTTPException(
                status_code=422, detail="limit must be a non-negative integer"
            )
        if limit < 0:
            raise HTTPException(
                status_code=422, detail="limit must be a non-negative integer"
            )
        return {
            "ok": True,
            "receipt": maintenance.migrate_originals_to_webp(
                limit=limit,
                dry_run=dry_run,
            ),
        }

    @router.post("/snapshot")
    def create_snapshot() -> dict:
        receipt = dict(maintenance.create_snapshot())
        receipt["filename"] = Path(str(receipt.pop("path"))).name
        return {"ok": True, "receipt": receipt}

    return router


from paths import data_dir as resolve_data_dir

ROOT = Path(__file__).resolve().parents[1]
router = build_router(resolve_data_dir())
page_router = APIRouter()


@page_router.get("/maintenance")
def maintenance_page() -> FileResponse:
    return FileResponse(
        ROOT / "web" / "maintenance.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

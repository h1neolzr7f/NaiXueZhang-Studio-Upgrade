"""Production queue: gallery assets waiting to enter Studio / batch generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paths import data_dir
from work_refs import WorkRef, WorkSelectionStore, public_work_id

QUEUE_PATH: Path | None = None


def queue_path() -> Path:
    return Path(QUEUE_PATH) if QUEUE_PATH is not None else data_dir() / "production_queue.json"


def _store() -> WorkSelectionStore:
    return WorkSelectionStore(queue_path(), kind="production_queue")


def list_refs() -> list[dict[str, Any]]:
    return _store().list_items()


def list_ids() -> list[int]:
    # Legacy Studio consumers operate on the site database.  Multi-gallery
    # workflows consume composite refs instead.
    return [
        int(item["work_id"])
        for item in list_refs()
        if item.get("gallery_id") == "site"
    ]


def has(work_id: int | str, gallery_id: str = "site") -> bool:
    return _store().has(WorkRef.parse(work_id, gallery_id))


def add(
    work_id: int | str,
    note: str = "",
    gallery_id: str = "site",
) -> dict[str, Any]:
    ref = WorkRef.parse(work_id, gallery_id)
    result = _store().add(
        ref,
        note=str(note or "").strip(),
        status="queued",
    )
    return {**result, "queued": True}


def remove(work_id: int | str, gallery_id: str = "site") -> dict[str, Any]:
    result = _store().remove(WorkRef.parse(work_id, gallery_id))
    return {**result, "queued": False}


def toggle(work_id: int | str, gallery_id: str = "site") -> dict[str, Any]:
    if has(work_id, gallery_id):
        return remove(work_id, gallery_id)
    return add(work_id, gallery_id=gallery_id)


def clear() -> dict[str, Any]:
    _store().clear()
    return {"ok": True, "count": 0}


def summary() -> dict[str, Any]:
    refs = list_refs()
    return {
        "ok": True,
        "count": len(refs),
        "ids": [public_work_id(item["work_id"]) for item in refs],
        "refs": refs,
        "updated_at": _store().load().get("updated_at") or "",
    }

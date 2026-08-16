"""Online discovery + favorite references + selected-only materialize."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from acquire.synthetic_provider import SyntheticProvider
from asset_lineage import lineage_from_materialize
from atomic_io import atomic_write_bytes, atomic_write_json
from library_lifecycle import RemoteCache, classify_asset, favorite_record
from library_writer import MaterializePage, discard_unreferenced_file, materialize_asset
from paths import data_dir
from remote_asset import RemoteAssetRef
from scripts.gallery_import_common import stable_work_id

_LOCK = threading.Lock()
_FAVORITES: dict[str, dict[str, Any]] = {}
_FAVORITES_LOADED = False
_CACHE: RemoteCache | None = None
_PROVIDER = SyntheticProvider()


def _favorites_path() -> Path:
    return Path(data_dir()) / "online_favorites.json"


def _load_favorites() -> dict[str, dict[str, Any]]:
    path = _favorites_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save_favorites(data: dict[str, dict[str, Any]]) -> None:
    atomic_write_json(_favorites_path(), data)


def _ensure_favorites() -> dict[str, dict[str, Any]]:
    global _FAVORITES_LOADED
    if not _FAVORITES_LOADED:
        _FAVORITES.update(_load_favorites())
        _FAVORITES_LOADED = True
    return _FAVORITES


def _cache() -> RemoteCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = RemoteCache(Path(data_dir()) / "remote_cache", max_items=32)
    return _CACHE


def reset_online_state_for_tests() -> None:
    global _CACHE, _PROVIDER, _FAVORITES_LOADED
    with _LOCK:
        _FAVORITES.clear()
        _FAVORITES_LOADED = False
    path = _favorites_path()
    path.unlink(missing_ok=True)
    _CACHE = None
    _PROVIDER = SyntheticProvider()


def unload_online_favorites_for_tests() -> None:
    """Simulate process restart: drop memory, keep the on-disk favorites file."""

    global _FAVORITES_LOADED
    with _LOCK:
        _FAVORITES.clear()
        _FAVORITES_LOADED = False


def set_provider_fail_mode(mode: str) -> None:
    _PROVIDER.fail_mode = str(mode or "")


def search_online(query: str, *, limit: int = 24) -> dict[str, Any]:
    try:
        cards = [_decorate(card.to_dict()) for card in _PROVIDER.search(query, limit=limit)]
        return {"ok": True, "section": "online", "items": cards, "provider_id": _PROVIDER.provider_id}
    except Exception as exc:
        return {
            "ok": False,
            "section": "online",
            "items": [],
            "error": type(exc).__name__,
            "message": str(exc),
            "local_library_available": True,
        }


def favorite_remote(remote_id: str) -> dict[str, Any]:
    card = _PROVIDER.fetch(remote_id)
    if card is None:
        raise KeyError(remote_id)
    record = favorite_record(card.ref, snapshot=card.to_dict())
    with _LOCK:
        favorites = _ensure_favorites()
        favorites[card.ref.qualified_id] = record
        _save_favorites(favorites)
    return {"ok": True, "favorite": True, "item": _decorate(card.to_dict())}


def list_favorites() -> list[dict[str, Any]]:
    with _LOCK:
        items = list(_ensure_favorites().values())
    decorated = []
    for item in items:
        ref = RemoteAssetRef.from_dict(item.get("remote_ref"))
        card = _PROVIDER.fetch(ref.remote_id)
        snapshot = dict(item.get("snapshot") or {})
        if card is None or not card.available:
            snapshot["available"] = False
            snapshot["lifecycle"] = classify_asset(
                remote_ref=ref,
                materialized=_is_materialized(ref),
                cached=_cache().get(ref) is not None,
            )
            snapshot.setdefault("title", snapshot.get("title") or ref.remote_id)
            snapshot["message"] = "来源暂不可用，仍保留收藏快照"
        else:
            snapshot = _decorate(card.to_dict())
        decorated.append(snapshot)
    return decorated


def add_to_my_library(remote_id: str, *, gallery_id: str = "codex") -> dict[str, Any]:
    card = _PROVIDER.fetch(remote_id)
    if card is None:
        raise KeyError(remote_id)
    payload = _PROVIDER.download_bytes(remote_id)
    cache_path = _cache().put(card.ref, payload)
    work_id = stable_work_id("synthetic", card.ref.remote_id)
    rel = f"online/{card.ref.provider_id}/{card.ref.remote_id}.png"
    from gallery_catalog import ensure_gallery_dirs, get_spec

    spec = get_spec(gallery_id)
    ensure_gallery_dirs(gallery_id)
    dest = spec.images_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    created = not dest.exists()
    atomic_write_bytes(dest, payload)
    digest = hashlib.sha256(payload).hexdigest()
    try:
        result = materialize_asset(
            gallery_id,
            work_id=work_id,
            title=card.title,
            remote_ref=card.ref,
            pages=[
                MaterializePage(
                    relative_path=rel,
                    source_url=card.ref.source_url,
                    source_sha256=digest,
                    prompt_text=card.prompt,
                )
            ],
            caption=card.author,
            tags="online,synthetic,NAI",
            source=card.ref.source_key,
            extra={"lineage": lineage_from_materialize(card.ref, source_sha256=digest).to_dict()},
        )
    except Exception:
        if created:
            discard_unreferenced_file(gallery_id, rel, dest)
        raise
    return {
        "ok": True,
        "gallery_id": gallery_id,
        "work_id": result.work_id,
        "work_ref": {"gallery_id": result.work_ref.gallery_id, "work_id": result.work_ref.work_id},
        "lifecycle": "materialized",
        "cache_path": str(cache_path),
        "remote_ref": card.ref.to_dict(),
    }


def derive_local_transform(remote_id: str, *, gallery_id: str = "codex") -> dict[str, Any]:
    """Free-safe local derive: copy bytes into a child work with lineage. No NovelAI HTTP."""

    card = _PROVIDER.fetch(remote_id)
    if card is None:
        raise KeyError(remote_id)
    parent = add_to_my_library(remote_id, gallery_id=gallery_id)
    payload = _PROVIDER.download_bytes(remote_id)
    digest = hashlib.sha256(payload).hexdigest()
    child_id = stable_work_id("synthetic-derive", card.ref.remote_id)
    rel = f"online/{card.ref.provider_id}/{card.ref.remote_id}-derive.png"
    from gallery_catalog import ensure_gallery_dirs, get_spec

    spec = get_spec(gallery_id)
    ensure_gallery_dirs(gallery_id)
    dest = spec.images_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    created = not dest.exists()
    atomic_write_bytes(dest, payload)
    lineage = lineage_from_materialize(
        card.ref,
        source_sha256=digest,
        parent_work_ref=f"{gallery_id}:{parent['work_id']}",
        recipe={"kind": "local_derive", "force_free": True, "paid": False},
        transform_summary="free-safe local derive; no NovelAI HTTP",
    )
    try:
        result = materialize_asset(
            gallery_id,
            work_id=child_id,
            title=f"{card.title} · derive",
            remote_ref=RemoteAssetRef.for_synthetic(f"{card.ref.remote_id}-derive"),
            pages=[
                MaterializePage(
                    relative_path=rel,
                    source_url=card.ref.source_url,
                    source_sha256=digest,
                    prompt_text=card.prompt,
                )
            ],
            caption=card.author,
            tags="online,synthetic,NAI,derive",
            source=f"synthetic-derive:{card.ref.remote_id}",
            extra={"lineage": lineage.to_dict()},
        )
    except Exception:
        if created:
            discard_unreferenced_file(gallery_id, rel, dest)
        raise
    return {
        "ok": True,
        "gallery_id": gallery_id,
        "work_id": result.work_id,
        "parent_work_id": parent["work_id"],
        "lineage": lineage.to_dict(),
        "lifecycle": "materialized",
        "paid": False,
        "transform": "local_derive",
    }


def _is_materialized(ref: RemoteAssetRef) -> bool:
    try:
        from gallery_catalog import get_db

        db = get_db("codex")
        row = db.conn.execute(
            "SELECT list_json FROM works WHERE id = ?",
            (stable_work_id("synthetic", ref.remote_id),),
        ).fetchone()
        return bool(row)
    except Exception:
        return False


def _decorate(card: dict[str, Any]) -> dict[str, Any]:
    ref = RemoteAssetRef.from_dict(card.get("ref"))
    cached = _cache().get(ref) is not None
    materialized = _is_materialized(ref)
    with _LOCK:
        favorited = ref.qualified_id in _ensure_favorites()
    card["favorite"] = favorited
    card["lifecycle"] = classify_asset(remote_ref=ref, materialized=materialized, cached=cached)
    card["section"] = "online" if card["lifecycle"] != "materialized" else "my_library"
    return card

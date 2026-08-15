"""Canonical gallery work references and atomic JSON selection persistence."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from atomic_io import atomic_write_text
from gallery_catalog import gallery_specs, normalize_gallery_id

JAVASCRIPT_MAX_SAFE_INTEGER = (2**53) - 1
SELECTION_ONLY_GALLERY_IDS = frozenset({"aitag-online", "codex-atlas"})
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}


def _lock_for_path(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False)).casefold()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def public_work_id(value: Any) -> int | str:
    """Keep small legacy IDs numeric and serialize unsafe IDs as text."""

    raw = str(value or "").strip()
    if not raw.isdecimal():
        raise ValueError("invalid work_id")
    number = int(raw)
    return number if number <= JAVASCRIPT_MAX_SAFE_INTEGER else raw


@dataclass(frozen=True, slots=True)
class WorkRef:
    gallery_id: str
    work_id: str

    @classmethod
    def parse(cls, work_id: Any, gallery_id: str | None = None) -> "WorkRef":
        raw_gid = str(gallery_id or "site").strip().lower()
        if raw_gid in SELECTION_ONLY_GALLERY_IDS:
            gid = raw_gid
        elif raw_gid not in gallery_specs():
            raise ValueError(f"unknown gallery_id: {raw_gid}")
        else:
            gid = normalize_gallery_id(raw_gid)
        raw = str(work_id or "").strip()
        if not raw.isdecimal() or int(raw) <= 0:
            raise ValueError("invalid work_id")
        return cls(gid, raw)

    @classmethod
    def from_item(cls, item: Any) -> "WorkRef":
        if not isinstance(item, dict):
            raise ValueError("invalid work reference")
        return cls.parse(item.get("work_id") or item.get("id"), item.get("gallery_id") or "site")

    @property
    def key(self) -> str:
        return f"{self.gallery_id}:{self.work_id}"

    def public(self) -> dict[str, str]:
        return {"gallery_id": self.gallery_id, "work_id": self.work_id, "key": self.key}


class WorkSelectionStore:
    """Deep persistence module shared by favorites and the production queue.

    Version 1 records with a bare work_id are read as site references and are
    rewritten as version 2 on the next mutation. Writes are atomic.
    """

    def __init__(self, path: Path, *, kind: str) -> None:
        self.path = path
        self.kind = kind
        self.lock = _lock_for_path(path)

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": 2, "kind": self.kind, "items": [], "updated_at": ""}

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty()
        if not isinstance(raw, dict):
            return self._empty()
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for original in raw.get("items") or []:
            try:
                ref = WorkRef.from_item(original)
            except (TypeError, ValueError):
                continue
            if ref.key in seen:
                continue
            seen.add(ref.key)
            item = dict(original)
            item.pop("id", None)
            item.update(ref.public())
            items.append(item)
        return {
            "schema_version": 2,
            "kind": self.kind,
            "items": items,
            "updated_at": str(raw.get("updated_at") or ""),
        }

    def save(self, data: dict[str, Any]) -> None:
        with self.lock:
            payload = dict(data)
            payload.update(schema_version=2, kind=self.kind, updated_at=_now_iso())
            atomic_write_text(
                self.path,
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            )

    def list_items(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.load()["items"])

    def list_refs(self) -> list[WorkRef]:
        return [WorkRef.from_item(item) for item in self.list_items()]

    def has(self, ref: WorkRef) -> bool:
        return any(current == ref for current in self.list_refs())

    def add(self, ref: WorkRef, **metadata: Any) -> dict[str, Any]:
        with self.lock:
            data = self.load()
            items = list(data["items"])
            existing = next((item for item in items if WorkRef.from_item(item) == ref), None)
            clean_meta = {k: v for k, v in metadata.items() if v not in (None, "")}
            if existing is None:
                items.insert(0, {**ref.public(), "added_at": _now_iso(), **clean_meta})
            else:
                existing.update(clean_meta)
            data["items"] = items
            self.save(data)
            return {"ok": True, **ref.public(), "count": len(items)}

    def remove(self, ref: WorkRef) -> dict[str, Any]:
        with self.lock:
            data = self.load()
            items = [item for item in data["items"] if WorkRef.from_item(item) != ref]
            data["items"] = items
            self.save(data)
            return {"ok": True, **ref.public(), "count": len(items)}

    def clear(self) -> None:
        with self.lock:
            self.save(self._empty())

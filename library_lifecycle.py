"""Remote / Cached / Materialized are facts, not a mutex state machine."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Literal

from remote_asset import RemoteAssetRef

Lifecycle = Literal["remote", "cached", "materialized"]


class RemoteCache:
    def __init__(self, root: Path, *, max_items: int = 64) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items
        self._lock = threading.Lock()
        self._order: list[str] = []

    def put(self, ref: RemoteAssetRef, payload: bytes) -> Path:
        key = ref.qualified_id.replace(":", "_")
        path = self.root / f"{key}.bin"
        path.write_bytes(payload)
        with self._lock:
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
            while len(self._order) > self.max_items:
                old = self._order.pop(0)
                (self.root / f"{old}.bin").unlink(missing_ok=True)
        return path

    def get(self, ref: RemoteAssetRef) -> bytes | None:
        path = self.root / f"{ref.qualified_id.replace(':', '_')}.bin"
        if not path.is_file():
            return None
        return path.read_bytes()

    def evict_all(self) -> None:
        with self._lock:
            for key in list(self._order):
                (self.root / f"{key}.bin").unlink(missing_ok=True)
            self._order.clear()


def classify_asset(
    *,
    remote_ref: RemoteAssetRef | None,
    materialized: bool,
    cached: bool,
) -> Lifecycle:
    if materialized:
        return "materialized"
    if cached:
        return "cached"
    if remote_ref is not None:
        return "remote"
    raise ValueError("asset has no remote, cache, or library fact")


def favorite_record(ref: RemoteAssetRef, *, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "kind": "remote_favorite",
        "remote_ref": ref.to_dict(),
        "snapshot": snapshot or {},
        "materialized": False,
    }


def load_work_remote_ref(list_json: str | None) -> RemoteAssetRef | None:
    if not list_json:
        return None
    try:
        payload = json.loads(list_json)
    except json.JSONDecodeError:
        return None
    raw = payload.get("remote_ref") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        return RemoteAssetRef.from_dict(raw)
    except ValueError:
        return None

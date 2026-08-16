"""In-process stub provider for cloud E2E. Never writes the library."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from remote_asset import RemoteAssetRef

from .provider_contract import RemoteCard


class SyntheticProvider:
    provider_id = "synthetic"

    def __init__(self, *, fail_mode: str = "") -> None:
        self.fail_mode = fail_mode
        self.catalog = {
            "syn-1": {
                "title": "合成角色 A",
                "prompt": "1girl, looking at viewer",
                "author": "fixture",
                "color": (220, 80, 90),
            },
            "syn-2": {
                "title": "合成角色 B",
                "prompt": "1boy, standing",
                "author": "fixture",
                "color": (80, 140, 220),
            },
        }

    def search(self, query: str, *, limit: int = 24) -> list[RemoteCard]:
        if self.fail_mode == "timeout":
            raise TimeoutError("synthetic provider timeout")
        if self.fail_mode == "unavailable":
            raise ConnectionError("synthetic provider unavailable")
        if self.fail_mode == "malformed":
            raise ValueError("synthetic provider returned malformed JSON")
        needle = str(query or "").lower()
        cards: list[RemoteCard] = []
        for remote_id, item in self.catalog.items():
            hay = f"{item['title']} {item['prompt']}".lower()
            if needle and needle not in hay:
                continue
            cards.append(self.fetch(remote_id))
            if len(cards) >= limit:
                break
        return cards

    def fetch(self, remote_id: str) -> RemoteCard | None:
        item = self.catalog.get(str(remote_id))
        if item is None:
            return None
        available = self.fail_mode not in {"unavailable", "unavailable_item", "timeout"}
        return RemoteCard(
            ref=RemoteAssetRef.for_synthetic(remote_id),
            title=item["title"],
            thumb_url=f"/api/online/synthetic/thumb/{remote_id}",
            prompt=item["prompt"],
            author=item["author"],
            rights="fixture",
            available=available,
            lifecycle="remote",
        )

    def download_bytes(self, remote_id: str) -> bytes:
        if self.fail_mode in {"unavailable", "timeout"}:
            raise ConnectionError("synthetic provider offline")
        item = self.catalog.get(str(remote_id))
        if item is None:
            raise KeyError(remote_id)
        image = Image.new("RGB", (64, 64), item["color"])
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from remote_asset import RemoteAssetRef


@dataclass
class RemoteCard:
    ref: RemoteAssetRef
    title: str
    thumb_url: str = ""
    prompt: str = ""
    author: str = ""
    rights: str = ""
    available: bool = True
    lifecycle: str = "remote"
    favorite: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ref"] = self.ref.to_dict()
        payload["qualified_id"] = self.ref.qualified_id
        return payload


class ProviderContract(Protocol):
    provider_id: str

    def search(self, query: str, *, limit: int = 24) -> list[RemoteCard]:
        ...

    def fetch(self, remote_id: str) -> RemoteCard | None:
        ...

    def download_bytes(self, remote_id: str) -> bytes:
        ...

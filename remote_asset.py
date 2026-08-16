"""Source-qualified remote identity. WorkRef stays the local public ID."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


IDENTITY_VERSION = 1


@dataclass(frozen=True, slots=True)
class RemoteAssetRef:
    provider_id: str
    remote_id: str
    source_url: str = ""
    source_key: str = ""
    identity_version: int = IDENTITY_VERSION

    def __post_init__(self) -> None:
        if not str(self.provider_id or "").strip():
            raise ValueError("provider_id is required")
        if not str(self.remote_id or "").strip():
            raise ValueError("remote_id is required")

    @property
    def qualified_id(self) -> str:
        return f"{self.provider_id}:{self.remote_id}:v{self.identity_version}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RemoteAssetRef":
        data = payload if isinstance(payload, dict) else {}
        return cls(
            provider_id=str(data.get("provider_id") or "").strip(),
            remote_id=str(data.get("remote_id") or "").strip(),
            source_url=str(data.get("source_url") or "").strip(),
            source_key=str(data.get("source_key") or data.get("source") or "").strip(),
            identity_version=int(data.get("identity_version") or IDENTITY_VERSION),
        )

    @classmethod
    def for_drop(cls, digest: str, *, folder: str = "", filename: str = "") -> "RemoteAssetRef":
        return cls(
            provider_id="local-drop",
            remote_id=str(digest),
            source_key=f"local-drop:{folder}/{filename}".strip("/"),
        )

    @classmethod
    def for_qq(cls, source_id: str, *, path: str = "") -> "RemoteAssetRef":
        return cls(provider_id="qq", remote_id=str(source_id), source_key=str(path or source_id))

    @classmethod
    def for_codex(cls, entry_id: str, *, source_key: str = "") -> "RemoteAssetRef":
        return cls(provider_id="codex", remote_id=str(entry_id), source_key=str(source_key or entry_id))

    @classmethod
    def for_pixiv(cls, artwork_id: str, *, source_url: str = "") -> "RemoteAssetRef":
        return cls(provider_id="pixiv", remote_id=str(artwork_id), source_url=str(source_url or ""))

    @classmethod
    def for_synthetic(cls, remote_id: str, *, source_url: str = "") -> "RemoteAssetRef":
        return cls(
            provider_id="synthetic",
            remote_id=str(remote_id),
            source_url=str(source_url or f"synthetic://{remote_id}"),
            source_key=f"synthetic:{remote_id}",
        )

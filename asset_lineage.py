"""Minimal queryable lineage. Not a general DAG."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from remote_asset import RemoteAssetRef


@dataclass(frozen=True)
class AssetLineage:
    provider_id: str = ""
    remote_id: str = ""
    source_url: str = ""
    source_sha256: str = ""
    acquired_at: str = ""
    author: str = ""
    rights: str = ""
    parent_work_ref: str = ""
    recipe_fingerprint: str = ""
    parent_generated_stem: str = ""
    transform_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def recipe_fingerprint(recipe: dict[str, Any] | None) -> str:
    raw = json.dumps(recipe or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lineage_from_materialize(
    remote_ref: RemoteAssetRef | None,
    *,
    source_sha256: str = "",
    acquired_at: str = "",
    author: str = "",
    rights: str = "",
    parent_work_ref: str = "",
    recipe: dict[str, Any] | None = None,
    transform_summary: str = "",
    parent_generated_stem: str = "",
) -> AssetLineage:
    return AssetLineage(
        provider_id=remote_ref.provider_id if remote_ref else "",
        remote_id=remote_ref.remote_id if remote_ref else "",
        source_url=remote_ref.source_url if remote_ref else "",
        source_sha256=source_sha256,
        acquired_at=acquired_at,
        author=author,
        rights=rights,
        parent_work_ref=parent_work_ref,
        recipe_fingerprint=recipe_fingerprint(recipe),
        parent_generated_stem=parent_generated_stem,
        transform_summary=transform_summary,
    )

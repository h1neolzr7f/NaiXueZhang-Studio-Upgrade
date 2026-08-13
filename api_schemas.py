"""Pydantic bodies for paid generation and crawler write endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CrawlerControlRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    target: str = "pixiv"
    phase: str = ""
    watch: bool = True
    task: dict[str, Any] = Field(default_factory=dict)
    limit: int = 1000
    restart: bool = False


class CharSwapBatchRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    targets: list[dict[str, Any]] = Field(default_factory=list)
    recipe: dict[str, Any] = Field(default_factory=dict)
    force_free: bool = True
    generate: bool = True
    preview_only: bool = False


class NaiGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    patched_comment: dict[str, Any]
    work_id: int | str | None = None
    page_index: int = 0
    source_gallery_id: str = "site"
    remote_work_id: str = ""
    work_id_str: str = ""
    source_title: str = ""
    source_thumb: str = ""
    copies: int = 1
    batch_count: int = 1
    seed_policy: str = ""
    force_free: bool = True
    prompt_profile: str = "native"
    token_id: str = ""

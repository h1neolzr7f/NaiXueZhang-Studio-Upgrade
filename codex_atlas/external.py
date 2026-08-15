"""Typed, read-only boundary for 法典图鉴 public JSON.

This module does not choose a host or make network calls.  Callers pass a
decoded payload and receive normalized books/entries that the Studio draft
path can consume as prompt text only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping
from urllib.parse import quote, urlparse


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any, *, limit: int = 2_000) -> str:
    return str(value or "").strip()[:limit]


def _path_segments(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace("\\", "/").split("/") if part.strip()]
        return tuple(parts[:12])
    if not isinstance(value, (list, tuple)):
        return ()
    parts = [_text(item, limit=80) for item in value]
    return tuple(part for part in parts if part)[:12]


def _character_prompts(value: Any) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list):
        return ()
    rows: list[dict[str, str]] = []
    for item in value[:16]:
        raw = _mapping(item)
        label = _text(raw.get("label") or raw.get("name"), limit=80)
        prompt = _text(raw.get("prompt") or raw.get("tags") or raw.get("text"), limit=8_000)
        negative = _text(raw.get("negative") or raw.get("uc"), limit=4_000)
        if not (label or prompt or negative):
            continue
        rows.append({"label": label, "prompt": prompt, "negative": negative})
    return tuple(rows)


def _image_name(value: Any) -> str:
    text = _text(value, limit=180)
    if not text or "/" in text or "\\" in text or text.startswith("."):
        return ""
    if ".." in text:
        return ""
    return text


def _entry_image_name(raw: Mapping[str, Any]) -> str:
    direct = _image_name(raw.get("image"))
    if direct:
        return direct
    images = raw.get("images")
    if isinstance(images, list) and images:
        first = images[0] if isinstance(images[0], Mapping) else {}
        return _image_name(first.get("path") or first.get("image"))
    return ""


@dataclass(frozen=True)
class CodexAtlasBook:
    book_id: str
    title: str = ""
    author: str = ""
    version: str = ""
    book_type: str = "codex"
    source: str = ""
    entry_count: int = 0
    imaged_count: int = 0
    nsfw: bool = False
    external: bool = False
    cover: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodexAtlasEntry:
    work_id: str
    book_id: str
    entry_id: str
    title: str = ""
    author: str = ""
    tags: str = ""
    negative: str = ""
    note: str = ""
    path: tuple[str, ...] = field(default_factory=tuple)
    character_prompts: tuple[dict[str, str], ...] = field(default_factory=tuple)
    image: str = ""
    original: str = ""
    nsfw: bool = False
    is_new: bool = False
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = list(self.path)
        data["character_prompts"] = [dict(item) for item in self.character_prompts]
        return data


@dataclass(frozen=True)
class CodexAtlasSearchPage:
    query: str
    book_id: str
    page: int
    page_size: int
    total: int
    has_more: bool
    entries: tuple[CodexAtlasEntry, ...] = field(default_factory=tuple)


def atlas_entry_is_safe(entry: CodexAtlasEntry) -> bool:
    return not bool(entry.nsfw)


def atlas_image_url(
    *,
    image_base: str,
    book_id: str,
    file_name: str,
    asset_rev: str = "",
) -> str:
    host = str(image_base or "").rstrip("/")
    name = _image_name(file_name)
    book = _text(book_id, limit=64)
    if not host or not name or not book:
        return ""
    parsed = urlparse(host)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return ""
    url = f"{host}/images/{quote(book, safe='')}/{quote(name, safe='')}"
    rev = _text(asset_rev, limit=40)
    if rev:
        url += f"?v={quote(rev, safe='')}"
    return url


def normalize_atlas_book(payload: Mapping[str, Any] | None) -> CodexAtlasBook | None:
    raw = _mapping(payload)
    book_id = _text(raw.get("id") or raw.get("book_id"), limit=64).casefold()
    if not book_id:
        return None
    data_url = _text(raw.get("dataUrl") or raw.get("data_url"), limit=500)
    return CodexAtlasBook(
        book_id=book_id,
        title=_text(raw.get("title") or book_id, limit=200),
        author=_text(raw.get("author"), limit=200),
        version=_text(raw.get("version"), limit=80),
        book_type=_text(raw.get("type") or "codex", limit=32).casefold() or "codex",
        source=_text(raw.get("source"), limit=300),
        entry_count=max(0, int(raw.get("entryCount") or raw.get("entry_count") or 0)),
        imaged_count=max(0, int(raw.get("imagedCount") or raw.get("imaged_count") or 0)),
        nsfw=bool(raw.get("nsfw")),
        external=bool(data_url),
        cover=_image_name(raw.get("cover")),
    )


def normalize_atlas_entry(
    payload: Mapping[str, Any] | None,
    *,
    book: CodexAtlasBook,
    source_url: str = "",
) -> CodexAtlasEntry | None:
    raw = _mapping(payload)
    entry_id = _text(raw.get("id") or raw.get("entry_id"), limit=180)
    if not entry_id:
        return None
    tags = _text(raw.get("tags") or raw.get("prompt") or raw.get("positive"), limit=8_000)
    negative = _text(raw.get("negative") or raw.get("uc"), limit=4_000)
    rating = _text(raw.get("rating"), limit=20).casefold()
    nsfw = bool(book.nsfw or raw.get("nsfw") or rating in {"nsfw", "r18", "r18g", "explicit"})
    return CodexAtlasEntry(
        work_id=f"{book.book_id}:{entry_id}",
        book_id=book.book_id,
        entry_id=entry_id,
        title=_text(raw.get("title") or entry_id, limit=200),
        author=_text(raw.get("author") or book.author, limit=200),
        tags=tags,
        negative=negative,
        note=_text(raw.get("note"), limit=2_000),
        path=_path_segments(raw.get("path")),
        character_prompts=_character_prompts(raw.get("characterPrompts") or raw.get("character_prompts")),
        image=_entry_image_name(raw),
        original=_image_name(raw.get("original")),
        nsfw=nsfw,
        is_new=bool(raw.get("isNew") or raw.get("is_new")),
        source_url=_text(source_url, limit=500),
    )


def normalize_atlas_search(
    entries: list[CodexAtlasEntry],
    *,
    query: str,
    book_id: str,
    page: int,
    page_size: int,
) -> CodexAtlasSearchPage:
    total = len(entries)
    start = max(0, (page - 1) * page_size)
    page_rows = tuple(entries[start:start + page_size])
    return CodexAtlasSearchPage(
        query=query,
        book_id=book_id,
        page=page,
        page_size=page_size,
        total=total,
        has_more=start + len(page_rows) < total,
        entries=page_rows,
    )

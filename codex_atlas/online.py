"""On-demand 法典图鉴 discovery client.

The official public release is treated as a remote prompt atlas, not as a
second gallery database.  The client only requests JSON from a fixed HTTPS
origin, keeps a bounded cache, and leaves image downloads to an explicit
cover proxy.  External-host books are rejected so this adapter cannot become
an SSRF primitive.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from aitag_core.storage.http_cache import DiskResponseCache

from .external import (
    CodexAtlasBook,
    CodexAtlasEntry,
    CodexAtlasSearchPage,
    atlas_entry_is_safe,
    atlas_image_url,
    normalize_atlas_book,
    normalize_atlas_entry,
    normalize_atlas_search,
)

ATLAS_SITE_URL = "https://novelai.quicktagcloud.com"
ATLAS_DATA_ORIGIN = "https://assets.quicktagcloud.com"
ATLAS_POINTER_URL = f"{ATLAS_DATA_ORIGIN}/data/current.json"
ATLAS_TIMEOUT_SECONDS = 30.0
ATLAS_CACHE_TTL_SECONDS = 600.0
ATLAS_CACHE_MAX_BYTES = 96 * 1024 * 1024
ATLAS_MAX_JSON_BYTES = 12 * 1024 * 1024
ATLAS_MAX_IMAGE_BYTES = 8 * 1024 * 1024
ATLAS_PAGE_SIZE = 60
DEFAULT_BOOK_ID = "suozhang"
DEFAULT_SFW_BOOKS = (
    "suozhang",
    "artist_nai45_strings",
    "composition_style",
    "qianteng",
    "jiegou_yuandian",
)

_BOOK_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,180}$")
_RELEASE_RE = re.compile(r"^r-[a-f0-9]{8,64}$")
_WORK_ID_RE = re.compile(r"^([a-z0-9_]{1,64}):([A-Za-z0-9._-]{1,180})$")
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,180}\.(?:jpe?g|png|webp)$", re.IGNORECASE)


class CodexAtlasClientError(RuntimeError):
    """A user-safe error raised when remote atlas discovery is unavailable."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_atlas_book_id(value: str) -> str:
    book_id = str(value or "").strip().casefold()
    if not _BOOK_ID_RE.fullmatch(book_id):
        raise ValueError("法典图鉴 book id is invalid")
    return book_id


def validate_atlas_entry_id(value: str) -> str:
    entry_id = str(value or "").strip()
    if not _ENTRY_ID_RE.fullmatch(entry_id):
        raise ValueError("法典图鉴 entry id is invalid")
    return entry_id


def parse_atlas_work_id(value: str) -> tuple[str, str]:
    match = _WORK_ID_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("法典图鉴 work id is invalid")
    return match.group(1), match.group(2)


def _validate_response_origin(response: Any, hostname: str) -> None:
    if getattr(response, "history", None):
        raise CodexAtlasClientError("法典图鉴 redirects are not accepted")
    response_url = getattr(response, "url", None)
    if response_url is None:
        return
    parsed = urlparse(str(response_url))
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname != hostname
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise CodexAtlasClientError("法典图鉴 response escaped the fixed HTTPS origin")


@dataclass(frozen=True)
class AtlasRelease:
    release: str
    pointer_url: str = ATLAS_POINTER_URL

    @property
    def data_base(self) -> str:
        return f"{ATLAS_DATA_ORIGIN}/data/releases/{self.release}"


class CodexAtlasClient:
    """Small synchronous client used by the FastAPI read/draft bridge."""

    def __init__(
        self,
        *,
        cache_root: Path | str | None = None,
        cache_ttl_seconds: float = ATLAS_CACHE_TTL_SECONDS,
        cache_max_bytes: int = ATLAS_CACHE_MAX_BYTES,
        timeout_seconds: float = ATLAS_TIMEOUT_SECONDS,
        http_client: Any | None = None,
    ) -> None:
        self.cache = DiskResponseCache(
            cache_root or Path("data") / ".cache" / "codex-atlas",
            ttl_seconds=cache_ttl_seconds,
            max_bytes=cache_max_bytes,
        )
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=float(timeout_seconds),
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "NaiXueZhang-Studio/codex-atlas"},
        )

    def _request_bytes(self, url: str, *, hostname: str, max_bytes: int) -> bytes:
        cached = self.cache.get(url)
        if cached:
            return cached
        try:
            response = self.http_client.get(url)
        except Exception as exc:
            raise CodexAtlasClientError(f"法典图鉴 request failed: {exc}") from exc
        status_code = int(getattr(response, "status_code", 0) or 0)
        _validate_response_origin(response, hostname)
        if 300 <= status_code < 400:
            raise CodexAtlasClientError("法典图鉴 redirects are not accepted", status_code=status_code)
        if status_code < 200 or status_code >= 300:
            raise CodexAtlasClientError(
                f"法典图鉴 returned HTTP {status_code}",
                status_code=status_code or None,
            )
        content = bytes(getattr(response, "content", b"") or b"")
        if not content:
            raise CodexAtlasClientError("法典图鉴 returned an empty payload", status_code=status_code)
        if len(content) > max_bytes:
            raise CodexAtlasClientError("法典图鉴 payload exceeded the local size limit")
        try:
            self.cache.put(url, content)
        except (OSError, ValueError):
            pass
        return content

    def _request_json(self, url: str) -> Mapping[str, Any] | list[Any]:
        raw = self._request_bytes(url, hostname="assets.quicktagcloud.com", max_bytes=ATLAS_MAX_JSON_BYTES)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexAtlasClientError("法典图鉴 returned invalid JSON") from exc
        if not isinstance(payload, (Mapping, list)):
            raise CodexAtlasClientError("法典图鉴 returned an unsupported JSON payload")
        return payload

    def get_release(self) -> AtlasRelease:
        payload = self._request_json(ATLAS_POINTER_URL)
        if not isinstance(payload, Mapping):
            raise CodexAtlasClientError("法典图鉴 release pointer is invalid")
        release = str(payload.get("release") or "").strip()
        if not _RELEASE_RE.fullmatch(release):
            raise CodexAtlasClientError("法典图鉴 release id is invalid")
        return AtlasRelease(release=release)

    def list_books(self, *, safe_only: bool = True) -> tuple[CodexAtlasBook, ...]:
        release = self.get_release()
        payload = self._request_json(f"{release.data_base}/codexes.json")
        if not isinstance(payload, list):
            raise CodexAtlasClientError("法典图鉴 book index is invalid")
        books: list[CodexAtlasBook] = []
        for item in payload:
            book = normalize_atlas_book(item if isinstance(item, Mapping) else None)
            if book is None or book.external:
                continue
            if safe_only and book.nsfw:
                continue
            books.append(book)
        return tuple(books)

    def _resolve_book(self, book_id: str) -> CodexAtlasBook:
        identifier = validate_atlas_book_id(book_id)
        books = {item.book_id: item for item in self.list_books(safe_only=False)}
        book = books.get(identifier)
        if book is None:
            raise CodexAtlasClientError("法典图鉴 book was not found", status_code=404)
        if book.external:
            raise CodexAtlasClientError("external-host 法典 are not fetched")
        return book

    def _download_book_entries(self, book: CodexAtlasBook) -> tuple[CodexAtlasBook, list[Mapping[str, Any]]]:
        release = self.get_release()
        payload = self._request_json(f"{release.data_base}/{book.book_id}.json")
        if not isinstance(payload, Mapping):
            raise CodexAtlasClientError("法典图鉴 book payload is invalid")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise CodexAtlasClientError("法典图鉴 book has no entries")
        meta = normalize_atlas_book(payload) or book
        if meta.external:
            raise CodexAtlasClientError("external-host 法典 are not fetched")
        return meta, [item for item in entries if isinstance(item, Mapping)]

    def load_entries(self, book_id: str, *, safe_only: bool = True) -> tuple[CodexAtlasBook, tuple[CodexAtlasEntry, ...]]:
        book = self._resolve_book(book_id)
        if safe_only and book.nsfw:
            raise CodexAtlasClientError("NSFW 法典 are locked until safe_only is disabled")
        book, raw_entries = self._download_book_entries(book)
        source_url = f"{ATLAS_SITE_URL}/?codex={book.book_id}"
        entries: list[CodexAtlasEntry] = []
        for item in raw_entries:
            entry = normalize_atlas_entry(item, book=book, source_url=source_url)
            if entry is None:
                continue
            if safe_only and not atlas_entry_is_safe(entry):
                continue
            entries.append(entry)
        return book, tuple(entries)

    def get_entry(self, work_id: str, *, safe_only: bool = True) -> CodexAtlasEntry:
        book_id, entry_id = parse_atlas_work_id(work_id)
        _book, entries = self.load_entries(book_id, safe_only=safe_only)
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise CodexAtlasClientError("法典图鉴 entry was not found", status_code=404)

    def search(
        self,
        *,
        query: str = "",
        book_id: str = "",
        page: int = 1,
        page_size: int = ATLAS_PAGE_SIZE,
        sort: str = "relevance",
        safe_only: bool = True,
    ) -> CodexAtlasSearchPage:
        page = max(1, min(int(page or 1), 10_000))
        page_size = max(1, min(int(page_size or ATLAS_PAGE_SIZE), 120))
        needle = str(query or "").strip()[:2_000].casefold()
        terms = [part for part in re.split(r"[\s,，、]+", needle) if part][:12]
        selected = str(book_id or "").strip().casefold()
        if selected:
            book_ids = [validate_atlas_book_id(selected)]
        else:
            book_ids = list(DEFAULT_SFW_BOOKS if safe_only else (DEFAULT_BOOK_ID,))
        collected: list[CodexAtlasEntry] = []
        for identifier in book_ids:
            try:
                _book, entries = self.load_entries(identifier, safe_only=safe_only)
            except CodexAtlasClientError:
                if selected:
                    raise
                continue
            for entry in entries:
                if terms and not _entry_matches(entry, terms):
                    continue
                collected.append(entry)
        ordered = _sort_entries(collected, sort=sort, query=needle)
        return normalize_atlas_search(
            ordered,
            query=needle,
            book_id=selected or "sfw-default",
            page=page,
            page_size=page_size,
        )

    def get_image(self, book_id: str, file_name: str) -> tuple[bytes, str]:
        identifier = validate_atlas_book_id(book_id)
        name = str(file_name or "").strip()
        if not _IMAGE_NAME_RE.fullmatch(name):
            raise ValueError("invalid 法典图鉴 image path")
        url = atlas_image_url(image_base=ATLAS_DATA_ORIGIN, book_id=identifier, file_name=name)
        if not url:
            raise ValueError("invalid 法典图鉴 image path")
        content = self._request_bytes(
            url,
            hostname="assets.quicktagcloud.com",
            max_bytes=ATLAS_MAX_IMAGE_BYTES,
        )
        suffix = name.rsplit(".", 1)[-1].casefold()
        content_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
        }.get(suffix, "image/jpeg")
        return content, content_type

    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "site_url": ATLAS_SITE_URL,
            "data_origin": ATLAS_DATA_ORIGIN,
            "cache": self.cache.stats(),
            "cache_ttl_seconds": self.cache.ttl_seconds,
        }

    def clear_cache(self) -> int:
        return self.cache.clear()

    def close(self) -> None:
        if self._owns_client:
            try:
                self.http_client.close()
            except Exception:
                pass


def _entry_matches(entry: CodexAtlasEntry, terms: list[str]) -> bool:
    hay = "\n".join(
        [
            entry.title,
            entry.tags,
            entry.negative,
            entry.note,
            entry.author,
            entry.book_id,
            " ".join(entry.path),
            " ".join(
                f"{item.get('label', '')} {item.get('prompt', '')} {item.get('negative', '')}"
                for item in entry.character_prompts
            ),
        ]
    ).casefold()
    return all(term in hay for term in terms)


def _sort_entries(entries: list[CodexAtlasEntry], *, sort: str, query: str) -> list[CodexAtlasEntry]:
    mode = str(sort or "relevance").strip().casefold()
    if mode == "title":
        return sorted(entries, key=lambda item: (item.title.casefold(), item.work_id))
    if mode == "recent":
        return sorted(entries, key=lambda item: (not item.is_new, item.work_id))
    if not query:
        return entries
    return sorted(
        entries,
        key=lambda item: (
            0 if query in item.title.casefold() else 1,
            0 if query in item.tags.casefold() else 1,
            item.work_id,
        ),
    )


__all__ = [
    "ATLAS_DATA_ORIGIN",
    "ATLAS_PAGE_SIZE",
    "ATLAS_SITE_URL",
    "DEFAULT_BOOK_ID",
    "CodexAtlasClient",
    "CodexAtlasClientError",
    "parse_atlas_work_id",
    "validate_atlas_book_id",
    "validate_atlas_entry_id",
]

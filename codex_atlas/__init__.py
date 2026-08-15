"""Read-only discovery adapter for 法典图鉴 (novelai.quicktagcloud.com).

This is an optional remote prompt atlas, not a second local gallery.
Callers fetch public JSON from the official R2 release, keep a bounded
cache, and never persist entries into the main catalog.
"""

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
from .online import (
    ATLAS_SITE_URL,
    CodexAtlasClient,
    CodexAtlasClientError,
    validate_atlas_book_id,
    validate_atlas_entry_id,
)

__all__ = [
    "ATLAS_SITE_URL",
    "CodexAtlasBook",
    "CodexAtlasClient",
    "CodexAtlasClientError",
    "CodexAtlasEntry",
    "CodexAtlasSearchPage",
    "atlas_entry_is_safe",
    "atlas_image_url",
    "normalize_atlas_book",
    "normalize_atlas_entry",
    "normalize_atlas_search",
    "validate_atlas_book_id",
    "validate_atlas_entry_id",
]

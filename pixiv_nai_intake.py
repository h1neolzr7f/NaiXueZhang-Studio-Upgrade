"""Verified Pixiv-to-gallery intake for NovelAI images only."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from PIL import Image

from atomic_io import atomic_write_text
from db import Database, _invalidate_scope_total_cache
from db_compression import compress_text
from gallery_asset_store import GalleryAssetStore, GalleryStorageQuotaExceeded
from gallery_snapshot import maintenance_mode_active
from nai_image_metadata import PARSER_VERSION, parse_nai_image
from paths import normalize_image_relative


DownloadImage = Callable[[str, Path], None]

# Permanent page-level rejections: do not re-download these pages on later crawls.
# Temporary failures stay retryable via the crawler quarantine ledger.
PERMANENT_REJECT_REASONS = frozenset(
    {
        "nai_metadata_missing",
        "thumbnail_missing",
        "file_too_large",
        "unsupported_format",
        "not_novelai",
        "software_not_novelai",
        "missing_comment",
        "invalid_comment",
        "empty_prompt",
    }
)


def _remove_work_from_selections(work_id: int, data_dir: Path) -> None:
    """Best-effort removal of a deleted work from favorites and the queue.

    Only runs when the intake writes into the runtime data directory; test
    harnesses with isolated data dirs are never allowed to touch the real
    selection files.
    """

    target = Path(data_dir).resolve()
    try:
        import favorites

        if Path(favorites.favorite_path()).resolve().parent == target:
            favorites.remove(work_id, "site")
    except Exception:
        pass
    try:
        import production_queue

        if Path(production_queue.QUEUE_PATH).resolve().parent == target:
            production_queue.remove(work_id, "site")
    except Exception:
        pass


class _BlockedWorkError(ValueError):
    """Raised when a work is blocked by the author blacklist or the manual
    blocked-collection list. The crawler records a skip instead of a failure."""

    def __init__(self, work_id: int, reason: str) -> None:
        super().__init__(f"blocked work {work_id}: {reason}")
        self.work_id = work_id
        self.reason = reason


@dataclass(frozen=True)
class PixivPage:
    source_page_index: int
    original_url: str
    thumbnail_url: str = ""


@dataclass(frozen=True)
class PixivWork:
    work_id: int
    user_id: int
    user_name: str
    title: str
    caption: str
    tags: tuple[str, ...]
    create_date: str
    total_view: int
    total_bookmarks: int
    pages: tuple[PixivPage, ...]
    work_type: int = 0
    x_restrict: int = 0
    pixiv_ai_type: int | None = None

    def fingerprint(self) -> str:
        payload = {
            "work_id": self.work_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "title": self.title,
            "caption": self.caption,
            "tags": self.tags,
            "create_date": self.create_date,
            "total_view": self.total_view,
            "total_bookmarks": self.total_bookmarks,
            "pages": [
                (page.source_page_index, page.original_url) for page in self.pages
            ],
            "work_type": self.work_type,
            "x_restrict": self.x_restrict,
            "pixiv_ai_type": self.pixiv_ai_type,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PageReceipt:
    source_page_index: int
    original_url: str
    status: str
    reason: str
    display_page_index: int | None = None
    local_path: str = ""


@dataclass(frozen=True)
class IntakeReceipt:
    work_id: int
    status: str
    accepted_pages: int
    rejected_pages: int
    pages: tuple[PageReceipt, ...]


class PixivNAIIntake:
    """Deep intake module: verify, normalize, persist, and receipt one Pixiv work."""

    def __init__(
        self,
        *,
        db: Database,
        images_dir: Path,
        staging_dir: Path,
        allowed_image_hosts: tuple[str, ...] = ("i.pximg.net",),
        max_download_bytes: int = 128 * 1024 * 1024,
        page_workers: int = 4,
        storage_quota_bytes: int = 0,
        thumbnail_only_pages: bool = False,
    ) -> None:
        self.db = db
        self.images_dir = Path(images_dir).resolve()
        self.staging_dir = Path(staging_dir).resolve()
        self.allowed_image_hosts = frozenset(host.lower() for host in allowed_image_hosts)
        self.max_download_bytes = max(1, int(max_download_bytes))
        self.page_workers = max(1, min(int(page_workers), 16))
        self.storage_quota_bytes = max(0, int(storage_quota_bytes))
        self.thumbnail_only_pages = bool(thumbnail_only_pages)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.asset_store = GalleryAssetStore(self.images_dir)
        # Crash window: assets are published before the DB commit. The dirty
        # flag lets the next startup quarantine files that never landed in
        # the database.
        self.data_dir = self.images_dir.parent
        self._dirty_flag = self.data_dir / ".intake_dirty"
        self.db._run(self._ensure_schema)
        self._reconcile_if_dirty()

    def _assert_writable(self) -> None:
        if maintenance_mode_active(self.data_dir):
            raise RuntimeError(
                "gallery maintenance mode active; intake writes are blocked"
            )

    def _mark_intake_dirty(self) -> None:
        atomic_write_text(self._dirty_flag, f"{os.getpid()}\n")

    def _clear_intake_dirty(self) -> None:
        self._dirty_flag.unlink(missing_ok=True)

    def _reconcile_if_dirty(self) -> dict[str, object] | None:
        """Quarantine orphan assets left by a crash between publish and commit."""

        if not self._dirty_flag.is_file():
            return None
        try:
            return self.quarantine_orphans()
        finally:
            self._clear_intake_dirty()

    def quarantine_orphans(self) -> dict[str, object]:
        """Move files under images/ that no works row references to _orphans/."""

        def action() -> list[str]:
            references: list[str] = []
            for row in self.db.conn.execute(
                "SELECT local_path FROM work_images "
                "WHERE downloaded = 1 AND TRIM(COALESCE(local_path, '')) <> ''"
            ).fetchall():
                references.append(normalize_image_relative(str(row["local_path"])))
            for row in self.db.conn.execute(
                "SELECT preview_path FROM works "
                "WHERE TRIM(COALESCE(preview_path, '')) <> ''"
            ).fetchall():
                references.append(normalize_image_relative(str(row["preview_path"])))
            return references

        referenced = self.db._run(action)
        result = self.asset_store.reconcile(
            referenced,
            quarantine=self.images_dir / "_orphans",
        )
        return dict(result)

    def _ensure_schema(self) -> None:
        self.db.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pixiv_nai_receipts (
                work_id INTEGER NOT NULL,
                source_page_index INTEGER NOT NULL,
                source_url TEXT NOT NULL,
                work_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                display_page_index INTEGER,
                local_path TEXT,
                source_sha256 TEXT,
                parser_version TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (work_id, source_page_index)
            )
            """
        )
        self.db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pixiv_nai_receipts_status "
            "ON pixiv_nai_receipts(status, updated_at)"
        )
        receipt_columns = {
            str(row["name"])
            for row in self.db.conn.execute(
                "PRAGMA table_info(pixiv_nai_receipts)"
            ).fetchall()
        }
        if "parser_version" not in receipt_columns:
            self.db.conn.execute(
                "ALTER TABLE pixiv_nai_receipts "
                f"ADD COLUMN parser_version TEXT NOT NULL DEFAULT '{PARSER_VERSION}'"
            )
        self.db.conn.commit()

    def ingest_work(self, work: PixivWork, download: DownloadImage) -> IntakeReceipt:
        self._validate_work(work)
        fingerprint = work.fingerprint()
        # Permanent "no NAI data" outcomes stay recorded and never re-download.
        permanent_skip = self._permanent_rejection_receipt(work)
        if permanent_skip is not None:
            return permanent_skip
        unchanged = self._unchanged_receipt(work, fingerprint)
        if unchanged is not None:
            return unchanged
        cached = self._cached_pages(work)
        if cached is not None:
            cached_images, cached_receipts = cached
            self._persist(work, fingerprint, cached_images, cached_receipts)
            accepted_count = len(cached_images)
            return IntakeReceipt(
                work_id=work.work_id,
                status="updated",
                accepted_pages=accepted_count,
                rejected_pages=len(cached_receipts) - accepted_count,
                pages=tuple(cached_receipts),
            )

        receipts: list[PageReceipt] = []
        accepted_images: list[dict[str, object]] = []
        newly_published: list[Path] = []
        permanent_page_rejects = self._permanent_page_reject_map(work.work_id)
        with tempfile.TemporaryDirectory(
            prefix=f"pixiv-{work.work_id}-",
            dir=self.staging_dir,
        ) as temporary:
            temporary_dir = Path(temporary)

            def stage_page(
                page: PixivPage,
            ) -> tuple[PixivPage, Path, str, str]:
                prior = permanent_page_rejects.get(page.source_page_index)
                if prior is not None and prior["source_url"] == page.original_url:
                    # Same page already permanently failed NAI collection — do not re-hit CDN.
                    return page, temporary_dir, "rejected", str(prior["reason"])
                use_thumbnail = (
                    self.thumbnail_only_pages and page.source_page_index > 0
                )
                if use_thumbnail and not page.thumbnail_url:
                    return page, temporary_dir, "rejected", "thumbnail_missing"
                if use_thumbnail:
                    source_url = page.thumbnail_url or page.original_url
                else:
                    source_url = page.original_url
                suffix = Path(urlparse(source_url).path).suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    suffix = ".img"
                staged = temporary_dir / f"p{page.source_page_index}{suffix}"
                try:
                    download(source_url, staged)
                    if not staged.is_file():
                        raise OSError("downloader did not create a file")
                    if staged.stat().st_size > self.max_download_bytes:
                        return page, staged, "rejected", "file_too_large"
                except Exception:
                    return page, staged, "failed", "download_error"
                return page, staged, "", ""

            ordered_pages = sorted(
                work.pages, key=lambda item: item.source_page_index
            )
            with ThreadPoolExecutor(
                max_workers=min(self.page_workers, max(1, len(ordered_pages))),
                thread_name_prefix="pixiv-nai-page",
            ) as executor:
                staged_pages = list(executor.map(stage_page, ordered_pages))

            # Thumbnail-only later pages require page 0 to have passed full NAI parse.
            p0_nai_ok = False
            for page, staged, failure_status, failure_reason in staged_pages:
                if failure_status:
                    receipts.append(
                        PageReceipt(
                            page.source_page_index,
                            page.original_url,
                            failure_status,
                            failure_reason,
                        )
                    )
                    continue

                display_index = len(accepted_images)
                use_thumbnail = (
                    self.thumbnail_only_pages and page.source_page_index > 0
                )
                if use_thumbnail:
                    # Space-saving: later pages store compressed previews only,
                    # but only when cover (p0) already proved NovelAI provenance.
                    if not p0_nai_ok:
                        receipts.append(
                            PageReceipt(
                                page.source_page_index,
                                page.original_url,
                                "rejected",
                                "thumbnail_requires_p0_nai",
                            )
                        )
                        continue
                    staged_sha256 = self._sha256(staged)
                    relative_path = (
                        Path("_thumbs")
                        / str(work.user_id)
                        / (
                            f"{work.work_id}_p{page.source_page_index}_"
                            f"{staged_sha256[:12]}.webp"
                        )
                    )
                    destination = (self.images_dir / relative_path).resolve()
                    self._assert_under_images(destination)
                    image = {
                        "work_id": work.work_id,
                        "author_id": work.user_id,
                        "image_type": "thumbnail",
                        "file_name": relative_path.name,
                        "image_path": relative_path.as_posix(),
                        "model": "",
                        "ai_json": "",
                        "prompt_text": "",
                        "page_index": display_index,
                        "source_page_index": page.source_page_index,
                        # Hash is finalized after WebP publish.
                        "source_sha256": staged_sha256,
                        "local_path": relative_path.as_posix(),
                        "downloaded": 1,
                        "_staged_path": str(staged),
                        "_compress_max_edge": 1280,
                        "_compress_quality": 80,
                    }
                    accepted_images.append(image)
                    receipts.append(
                        PageReceipt(
                            page.source_page_index,
                            page.original_url,
                            "accepted",
                            "thumbnail",
                            display_page_index=display_index,
                            local_path=relative_path.as_posix(),
                        )
                    )
                    continue

                parsed = parse_nai_image(staged)
                if not parsed.accepted:
                    receipts.append(
                        PageReceipt(
                            page.source_page_index,
                            page.original_url,
                            "rejected",
                            parsed.reason or "nai_metadata_missing",
                        )
                    )
                    continue

                # Metadata is extracted from the staged original first; on-disk
                # storage is a compressed WebP to maximize space savings.
                staged_sha256 = self._sha256(staged)
                relative_path = (
                    Path("NAI")
                    / str(work.user_id)
                    / (
                        f"{work.work_id}_p{display_index}_"
                        f"{staged_sha256[:12]}.webp"
                    )
                )
                destination = (self.images_dir / relative_path).resolve()
                self._assert_under_images(destination)
                canonical = parsed.canonical_metadata()
                image = {
                    "work_id": work.work_id,
                    "author_id": work.user_id,
                    "image_type": "NAI",
                    "file_name": relative_path.name,
                    "image_path": relative_path.as_posix(),
                    "model": parsed.model,
                    "ai_json": canonical,
                    "prompt_text": parsed.prompt,
                    "page_index": display_index,
                    "source_page_index": page.source_page_index,
                    "source_sha256": staged_sha256,
                    "local_path": relative_path.as_posix(),
                    "downloaded": 1,
                    "_staged_path": str(staged),
                    "_compress_max_edge": self.asset_store.original_max_edge,
                    "_compress_quality": self.asset_store.original_quality,
                }
                accepted_images.append(image)
                if page.source_page_index == 0:
                    p0_nai_ok = True
                receipts.append(
                    PageReceipt(
                        page.source_page_index,
                        page.original_url,
                        "accepted",
                        "accepted",
                        display_page_index=display_index,
                        local_path=relative_path.as_posix(),
                    )
                )

            if any(receipt.status == "failed" for receipt in receipts):
                deferred = [
                    (
                        PageReceipt(
                            receipt.source_page_index,
                            receipt.original_url,
                            "failed",
                            "work_incomplete",
                        )
                        if receipt.status == "accepted"
                        else receipt
                    )
                    for receipt in receipts
                ]
                self._persist_receipts_only(
                    work,
                    fingerprint,
                    deferred,
                    accepted_images,
                )
                return IntakeReceipt(
                    work_id=work.work_id,
                    status="failed",
                    accepted_pages=0,
                    rejected_pages=len(deferred),
                    pages=tuple(deferred),
                )

            additional_bytes = sum(
                Path(str(image["_staged_path"])).stat().st_size
                for image in accepted_images
            )
            if not self.asset_store.has_capacity(
                additional_bytes, quota_bytes=self.storage_quota_bytes
            ):
                raise GalleryStorageQuotaExceeded(
                    f"gallery storage quota cannot accept {additional_bytes} more bytes"
                )
            self._mark_intake_dirty()
            try:
                newly_published = self._publish_staged_assets(accepted_images)
                for image in accepted_images:
                    image.pop("_staged_path", None)
            except Exception:
                self._clear_intake_dirty()
                raise

        try:
            self._persist(work, fingerprint, accepted_images, receipts)
        except Exception:
            self._remove_assets(newly_published)
            self._clear_intake_dirty()
            raise
        self._clear_intake_dirty()
        accepted_count = len(accepted_images)
        rejected_count = len(receipts) - accepted_count
        if accepted_count == len(receipts) and accepted_count:
            status = "accepted"
        elif accepted_count:
            status = "partial"
        else:
            status = "rejected"
        return IntakeReceipt(
            work_id=work.work_id,
            status=status,
            accepted_pages=accepted_count,
            rejected_pages=rejected_count,
            pages=tuple(receipts),
        )
    def _assert_not_blocked(self, work: PixivWork) -> None:
        """Skip works whose author is blacklisted or that are on the manual
        blocked-collection list. Raises a typed error so the crawler can
        record the skip without treating it as a failure."""
        blocked_work = self.db.conn.execute(
            "SELECT 1 FROM blocked_collection WHERE work_id = ?", (work.work_id,)
        ).fetchone()
        if blocked_work:
            raise _BlockedWorkError(work.work_id, "work in blocked_collection")
        row = self.db.conn.execute(
            "SELECT scope FROM author_blacklist WHERE author_id = ?", (work.user_id,)
        ).fetchone()
        if row and row["scope"] in ("crawl", "both"):
            raise _BlockedWorkError(work.work_id, f"author {work.user_id} blacklisted")

    def _validate_work(self, work: PixivWork) -> None:
        if work.work_id <= 0 or work.user_id <= 0:
            raise ValueError("Pixiv work and user identifiers must be positive")
        self._assert_not_blocked(work)
        indexes = [page.source_page_index for page in work.pages]
        if any(index < 0 for index in indexes) or len(set(indexes)) != len(indexes):
            raise ValueError("Pixiv source page indexes must be unique and non-negative")
        for page in work.pages:
            parsed = urlparse(page.original_url)
            if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self.allowed_image_hosts:
                raise ValueError("Pixiv original image URL is not on an allowed HTTPS host")
            if page.thumbnail_url:
                thumb_parsed = urlparse(page.thumbnail_url)
                if (
                    thumb_parsed.scheme != "https"
                    or (thumb_parsed.hostname or "").lower() not in self.allowed_image_hosts
                ):
                    raise ValueError("Pixiv thumbnail URL is not on an allowed HTTPS host")

    def _permanent_page_reject_map(self, work_id: int) -> dict[int, dict[str, str]]:
        """Map source_page_index -> permanent reject info for skip-on-re-ingest."""

        rows = self._receipt_rows(
            work_id,
            "source_page_index, source_url, status, reason, parser_version",
        )
        mapping: dict[int, dict[str, str]] = {}
        p0_permanent = any(
            int(row["source_page_index"]) == 0
            and str(row["status"]) == "rejected"
            and str(row["reason"] or "") in PERMANENT_REJECT_REASONS
            and str(row["parser_version"]) == PARSER_VERSION
            for row in rows
        )
        for row in rows:
            if str(row["parser_version"]) != PARSER_VERSION:
                continue
            if str(row["status"]) != "rejected":
                continue
            reason = str(row["reason"] or "")
            # 派生拒绝仅在 p0 永久拒绝时视为永久，否则保留重试机会
            if reason not in PERMANENT_REJECT_REASONS and not (
                p0_permanent
                and int(row["source_page_index"]) > 0
                and reason == "thumbnail_requires_p0_nai"
            ):
                continue
            mapping[int(row["source_page_index"])] = {
                "source_url": str(row["source_url"] or ""),
                "reason": reason,
            }
        return mapping

    def _permanent_rejection_receipt(
        self,
        work: PixivWork,
    ) -> IntakeReceipt | None:
        """Skip re-crawl when every page already permanently failed NAI collection.

        Records stay in ``pixiv_nai_receipts`` so maintenance can audit or purge
        later without re-hitting Pixiv for works that never produce NAI data.
        """

        rows = self._receipt_rows(
            work.work_id,
            "source_page_index, source_url, status, reason, "
            "display_page_index, local_path, parser_version",
        )
        pages = sorted(work.pages, key=lambda item: item.source_page_index)
        if not rows or len(rows) != len(pages):
            return None
        # thumbnail_requires_p0_nai 是封面页失败的派生拒绝：仅当 p0 本身是永久
        # 拒绝时它才确定不可恢复，此时整作应跳过；p0 是临时失败（failed）则
        # 不满足下面的条件，后续页仍会重新评估，避免只收封面的数据残缺。
        p0_permanent = any(
            int(row["source_page_index"]) == 0
            and str(row["status"]) == "rejected"
            and str(row["reason"] or "") in PERMANENT_REJECT_REASONS
            and str(row["parser_version"]) == PARSER_VERSION
            for row in rows
        )
        page_receipts: list[PageReceipt] = []
        for row, page in zip(rows, pages, strict=True):
            status = str(row["status"])
            reason = str(row["reason"] or "")
            reason_permanent = reason in PERMANENT_REJECT_REASONS or (
                p0_permanent
                and page.source_page_index > 0
                and reason == "thumbnail_requires_p0_nai"
            )
            if (
                int(row["source_page_index"]) != page.source_page_index
                or str(row["source_url"]) != page.original_url
                or str(row["parser_version"]) != PARSER_VERSION
                or status != "rejected"
                or not reason_permanent
            ):
                return None
            page_receipts.append(
                PageReceipt(
                    source_page_index=page.source_page_index,
                    original_url=page.original_url,
                    status=status,
                    reason=reason,
                    display_page_index=(
                        int(row["display_page_index"])
                        if row["display_page_index"] is not None
                        else None
                    ),
                    local_path=str(row["local_path"] or ""),
                )
            )
        # Fully rejected permanent works must not linger as gallery entries.
        if self.db.get_work_detail(work.work_id) is not None:
            return None
        return IntakeReceipt(
            work_id=work.work_id,
            status="unchanged",
            accepted_pages=0,
            rejected_pages=len(page_receipts),
            pages=tuple(page_receipts),
        )

    def _unchanged_receipt(
        self,
        work: PixivWork,
        fingerprint: str,
    ) -> IntakeReceipt | None:
        rows = self._receipt_rows(
            work.work_id,
            "source_page_index, source_url, status, reason, "
            "display_page_index, local_path, source_sha256, work_fingerprint, parser_version",
        )
        pages = sorted(work.pages, key=lambda item: item.source_page_index)
        if len(rows) != len(pages):
            return None
        accepted = 0
        page_receipts: list[PageReceipt] = []
        for row, page in zip(rows, pages, strict=True):
            if (
                int(row["source_page_index"]) != page.source_page_index
                or str(row["source_url"]) != page.original_url
                or str(row["work_fingerprint"]) != fingerprint
                or str(row["parser_version"]) != PARSER_VERSION
                or str(row["status"]) == "failed"
            ):
                return None
            local_path = normalize_image_relative(str(row["local_path"] or ""))
            if str(row["status"]) == "accepted":
                asset = (self.images_dir / local_path).resolve()
                self._assert_under_images(asset)
                expected_sha256 = str(row["source_sha256"] or "")
                if (
                    not asset.is_file()
                    or not expected_sha256
                    or self._sha256(asset) != expected_sha256
                ):
                    return None
                accepted += 1
            elif (
                str(row["status"]) == "rejected"
                and str(row["reason"] or "") not in PERMANENT_REJECT_REASONS
                and str(row["reason"] or "") not in {"thumbnail", "accepted"}
            ):
                # Non-permanent soft rejects still re-evaluate on content change.
                pass
            page_receipts.append(
                PageReceipt(
                    source_page_index=page.source_page_index,
                    original_url=page.original_url,
                    status=str(row["status"]),
                    reason=str(row["reason"]),
                    display_page_index=(
                        int(row["display_page_index"])
                        if row["display_page_index"] is not None
                        else None
                    ),
                    local_path=local_path,
                )
            )
        detail = self.db.get_work_detail(work.work_id)
        if bool(accepted) != bool(detail):
            return None
        return IntakeReceipt(
            work_id=work.work_id,
            status="unchanged",
            accepted_pages=accepted,
            rejected_pages=len(page_receipts) - accepted,
            pages=tuple(page_receipts),
        )

    def _cached_pages(
        self,
        work: PixivWork,
    ) -> tuple[list[dict[str, object]], list[PageReceipt]] | None:
        rows = self._receipt_rows(
            work.work_id,
            "source_page_index, source_url, status, reason, display_page_index, "
            "local_path, source_sha256, parser_version",
        )
        pages = sorted(work.pages, key=lambda item: item.source_page_index)
        if len(rows) != len(pages):
            return None
        detail = self.db.get_work_detail(work.work_id)
        detail_images = {
            int(image.get("source_page_index")): dict(image)
            for image in ((detail or {}).get("images") or [])
            if isinstance(image, dict) and image.get("source_page_index") is not None
        }
        images: list[dict[str, object]] = []
        receipts: list[PageReceipt] = []
        for row, page in zip(rows, pages, strict=True):
            status = str(row["status"])
            reason = str(row["reason"])
            if (
                int(row["source_page_index"]) != page.source_page_index
                or str(row["source_url"]) != page.original_url
                or str(row["parser_version"]) != PARSER_VERSION
                or status == "failed"
                or reason == "file_too_large"
            ):
                return None
            display_index = (
                int(row["display_page_index"])
                if row["display_page_index"] is not None
                else None
            )
            local_path = normalize_image_relative(str(row["local_path"] or ""))
            if status == "accepted":
                image = detail_images.get(page.source_page_index)
                asset = (self.images_dir / local_path).resolve()
                self._assert_under_images(asset)
                expected_sha256 = str(row["source_sha256"] or "")
                if (
                    image is None
                    or not asset.is_file()
                    or not expected_sha256
                    or self._sha256(asset) != expected_sha256
                ):
                    return None
                image["page_index"] = len(images)
                image["file_name"] = asset.name
                image["local_path"] = local_path
                image["image_path"] = local_path
                image["downloaded"] = 1
                image["source_sha256"] = str(row["source_sha256"] or "")
                images.append(image)
                display_index = int(image["page_index"])
            receipts.append(
                PageReceipt(
                    source_page_index=page.source_page_index,
                    original_url=page.original_url,
                    status=status,
                    reason=reason,
                    display_page_index=display_index,
                    local_path=local_path,
                )
            )
        if images and detail is None:
            return None
        return images, receipts

    def _persist(
        self,
        work: PixivWork,
        fingerprint: str,
        images: list[dict[str, object]],
        receipts: list[PageReceipt],
    ) -> None:
        self._assert_writable()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        current_paths = {
            str(path)
            for image in images
            for path in (image.get("local_path"), image.get("thumbnail_path"))
            if path
        }
        receipt_by_source_page = {
            receipt.source_page_index: receipt for receipt in receipts
        }

        def action() -> set[str]:
            try:
                self.db.conn.execute("BEGIN IMMEDIATE")
                old_paths = {
                    str(row["local_path"] or "")
                    for row in self.db.conn.execute(
                        "SELECT local_path FROM work_images WHERE work_id = ?",
                        (work.work_id,),
                    ).fetchall()
                    if row["local_path"]
                }
                old_preview = self.db.conn.execute(
                    "SELECT preview_path FROM works WHERE id = ?", (work.work_id,)
                ).fetchone()
                if old_preview and old_preview["preview_path"]:
                    old_paths.add(str(old_preview["preview_path"]))
                self.db.conn.execute(
                    "DELETE FROM pixiv_nai_receipts WHERE work_id = ?",
                    (work.work_id,),
                )
                for receipt in receipts:
                    source_sha256 = ""
                    if receipt.display_page_index is not None:
                        source_sha256 = str(
                            images[receipt.display_page_index].get("source_sha256") or ""
                        )
                    self.db.conn.execute(
                        """
                        INSERT INTO pixiv_nai_receipts(
                            work_id, source_page_index, source_url, work_fingerprint,
                            status, reason, display_page_index, local_path,
                            source_sha256, parser_version, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            work.work_id,
                            receipt.source_page_index,
                            receipt.original_url,
                            fingerprint,
                            receipt.status,
                            receipt.reason,
                            receipt.display_page_index,
                            receipt.local_path,
                            source_sha256,
                            PARSER_VERSION,
                            now,
                        ),
                    )
                if images:
                    item = self._work_item(work, images)
                    public_images = [
                        {
                            key: value
                            for key, value in image.items()
                            if key not in {"source_url", "source_sha256", "_staged_path"}
                        }
                        for image in images
                    ]
                    detail = {"work": item, "images": public_images}
                    preview_path = str(
                        images[0].get("thumbnail_path") or images[0]["local_path"]
                    )
                    self.db.conn.execute(
                        """
                        INSERT INTO works(
                            id, user_id, user_name, source_url, title, caption, tags,
                            ai_type, create_date, image_count, total_view,
                            total_bookmarks, list_json, detail_json, preview_path,
                            preview_downloaded, crawled_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'NAI', ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            user_id=excluded.user_id, user_name=excluded.user_name,
                            source_url=excluded.source_url, title=excluded.title,
                            caption=excluded.caption, tags=excluded.tags,
                            ai_type='NAI', create_date=excluded.create_date,
                            image_count=excluded.image_count,
                            total_view=excluded.total_view,
                            total_bookmarks=excluded.total_bookmarks,
                            list_json=excluded.list_json,
                            detail_json=excluded.detail_json,
                            preview_path=excluded.preview_path,
                            preview_downloaded=1, crawled_at=excluded.crawled_at
                        """,
                        (
                            work.work_id,
                            work.user_id,
                            work.user_name,
                            f"https://www.pixiv.net/artworks/{work.work_id}",
                            work.title,
                            work.caption,
                            item["tags"],
                            work.create_date,
                            len(images),
                            work.total_view,
                            work.total_bookmarks,
                            json.dumps(item, ensure_ascii=False),
                            compress_text(json.dumps(detail, ensure_ascii=False)),
                            preview_path,
                            now,
                        ),
                    )
                    self.db.conn.execute(
                        "DELETE FROM work_images WHERE work_id = ?", (work.work_id,)
                    )
                    for image in images:
                        raw_ai = image.get("ai_json")
                        if raw_ai in ("", None):
                            ai_blob = None
                        elif isinstance(raw_ai, (dict, list)):
                            ai_blob = compress_text(
                                json.dumps(raw_ai, ensure_ascii=False)
                            )
                        else:
                            ai_blob = compress_text(str(raw_ai))
                        image_type = str(image.get("image_type") or "NAI").strip() or "NAI"
                        self.db.conn.execute(
                            """
                            INSERT INTO work_images(
                                work_id, author_id, image_type, file_name, image_path,
                                model, ai_json, prompt_text, page_index,
                                source_page_index, source_url, source_sha256,
                                local_path, downloaded
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                            """,
                            (
                                work.work_id,
                                work.user_id,
                                image_type,
                                image["file_name"],
                                image["image_path"],
                                image["model"],
                                ai_blob,
                                image["prompt_text"],
                                image["page_index"],
                                image["source_page_index"],
                                receipt_by_source_page[
                                    int(image["source_page_index"])
                                ].original_url,
                                image["source_sha256"],
                                image["local_path"],
                            ),
                        )
                    self.db._sync_work_fts(work.work_id)
                    self.db._sync_prompt_fts(work.work_id)
                else:
                    self.db.conn.execute(
                        "DELETE FROM work_images WHERE work_id = ?", (work.work_id,)
                    )
                    self.db.conn.execute("DELETE FROM works WHERE id = ?", (work.work_id,))
                    self.db.conn.execute(
                        "DELETE FROM works_fts WHERE work_id = ?", (work.work_id,)
                    )
                    self.db.conn.execute(
                        "DELETE FROM prompt_fts WHERE work_id = ?", (work.work_id,)
                    )
                    self.db.conn.execute(
                        "DELETE FROM prompt_work_fts WHERE work_id = ?", (work.work_id,)
                    )
                self.db._sync_nai_tag_index(work.work_id)
                self.db.conn.commit()
                _invalidate_scope_total_cache()
                return old_paths
            except Exception:
                self.db.conn.rollback()
                raise

        old_paths = self.db._run(action)
        if not images:
            # The work row is gone; drop dangling selection references so
            # favorites/queue never point at a non-existent work.
            _remove_work_from_selections(work.work_id, self.data_dir)
        for relative in old_paths - current_paths:
            obsolete = (self.images_dir / relative).resolve()
            self._assert_under_images(obsolete)
            if obsolete.is_file():
                obsolete.unlink()

    def _persist_receipts_only(
        self,
        work: PixivWork,
        fingerprint: str,
        receipts: list[PageReceipt],
        verified_images: list[dict[str, object]],
    ) -> None:
        """Record a retryable attempt without mutating the visible gallery."""

        self._assert_writable()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sha_by_source_page = {
            int(image["source_page_index"]): str(image.get("source_sha256") or "")
            for image in verified_images
        }

        def action() -> None:
            try:
                self.db.conn.execute("BEGIN IMMEDIATE")
                self.db.conn.execute(
                    "DELETE FROM pixiv_nai_receipts WHERE work_id = ?",
                    (work.work_id,),
                )
                self.db.conn.executemany(
                    """
                    INSERT INTO pixiv_nai_receipts(
                        work_id, source_page_index, source_url, work_fingerprint,
                        status, reason, display_page_index, local_path,
                        source_sha256, parser_version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, '', ?, ?, ?)
                    """,
                    [
                        (
                            work.work_id,
                            receipt.source_page_index,
                            receipt.original_url,
                            fingerprint,
                            receipt.status,
                            receipt.reason,
                            sha_by_source_page.get(receipt.source_page_index, ""),
                            PARSER_VERSION,
                            now,
                        )
                        for receipt in receipts
                    ],
                )
                self.db.conn.commit()
            except Exception:
                self.db.conn.rollback()
                raise

        self.db._run(action)

    @staticmethod
    def _work_item(
        work: PixivWork,
        images: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "id": work.work_id,
            "userId": work.user_id,
            "userName": work.user_name,
            "type": work.work_type,
            "title": work.title,
            "caption": work.caption,
            "tags": json.dumps(work.tags, ensure_ascii=False),
            "create_date": work.create_date,
            "accepted_source_pages": [
                int(image["source_page_index"]) for image in images
            ],
            "source_page_count": len(work.pages),
            "image_count": len(images),
            "ai_png": 1,
            "AI_type": "NAI",
            "ai_type": "NAI",
            "total_view": work.total_view,
            "total_bookmarks": work.total_bookmarks,
            "x_restrict": work.x_restrict,
            "rating": {1: "R-18", 2: "R-18G"}.get(work.x_restrict, ""),
            "source": "pixiv-direct",
        }

    def _receipt_rows(self, work_id: int, columns: str):
        def action():
            return self.db.conn.execute(
                f"""
                SELECT {columns}
                FROM pixiv_nai_receipts
                WHERE work_id = ?
                ORDER BY source_page_index
                """,
                (work_id,),
            ).fetchall()

        return self.db._run(action)

    def _assert_under_images(self, path: Path) -> None:
        try:
            path.relative_to(self.images_dir)
        except ValueError as exc:
            raise ValueError("gallery asset path escapes images directory") from exc

    @staticmethod
    def _verified_extension(source: Path) -> str:
        with Image.open(source) as image:
            image_format = str(image.format or "").upper()
        return {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(
            image_format,
            source.suffix.lower() if source.suffix else ".img",
        )

    def _publish_staged_assets(
        self, images: list[dict[str, object]]
    ) -> list[Path]:
        published: list[Path] = []
        try:
            for image in images:
                source = Path(str(image["_staged_path"]))
                # NAI text chunks live only on the staged original. Re-verify
                # before compression, then store a compact WebP for browsing.
                if image.get("image_type") != "thumbnail":
                    if not parse_nai_image(source).accepted:
                        raise ValueError("staged gallery asset lost verified NAI metadata")

                relative = str(image["local_path"])
                if not relative.lower().endswith(".webp"):
                    relative = str(Path(relative).with_suffix(".webp").as_posix())
                    image["local_path"] = relative
                    image["image_path"] = relative
                    image["file_name"] = Path(relative).name

                destination = (self.images_dir / relative).resolve()
                self._assert_under_images(destination)
                existed = destination.exists()
                max_edge = int(image.get("_compress_max_edge") or self.asset_store.original_max_edge)
                quality = int(image.get("_compress_quality") or self.asset_store.original_quality)
                published_relative = self.asset_store.publish_compressed(
                    source,
                    relative,
                    max_edge=max_edge,
                    quality=quality,
                )
                image["local_path"] = published_relative
                image["image_path"] = published_relative
                image["file_name"] = Path(published_relative).name
                destination = (self.images_dir / published_relative).resolve()
                image["source_sha256"] = self._sha256(destination)
                if not existed:
                    published.append(destination)

                if image.get("image_type") == "thumbnail":
                    # Space-saving pages are already a compact WebP preview.
                    image["thumbnail_path"] = str(image["local_path"])
                    image.pop("_compress_max_edge", None)
                    image.pop("_compress_quality", None)
                    continue

                thumbnail_relative = self.asset_store.thumbnail_relative(
                    str(image["local_path"])
                )
                thumbnail = (self.images_dir / thumbnail_relative).resolve()
                thumbnail_existed = thumbnail.is_file()
                image["thumbnail_path"] = self.asset_store.ensure_thumbnail(
                    str(image["local_path"])
                )
                if not thumbnail_existed:
                    published.append(thumbnail)
                image.pop("_compress_max_edge", None)
                image.pop("_compress_quality", None)
            return published
        except Exception:
            self._remove_assets(published)
            raise

    def _remove_assets(self, paths: list[Path]) -> None:
        for path in paths:
            resolved = path.resolve()
            self._assert_under_images(resolved)
            if resolved.is_file():
                resolved.unlink()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

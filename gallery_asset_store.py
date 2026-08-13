"""Local asset lifecycle for verified Gallery Works."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

from paths import canonical_path, path_is_within, relative_to_canonical


class GalleryStorageQuotaExceeded(RuntimeError):
    retryable = False
    reason = "storage_quota_exceeded"


def compress_image_for_storage(
    source: Path,
    destination: Path,
    *,
    max_edge: int = 4096,
    quality: int = 85,
    method: int = 6,
) -> Path:
    """Re-encode an image as WebP for compact local storage.

    NAI metadata must already be extracted into the database before calling this;
    WebP does not keep NovelAI PNG text chunks.
    """

    source = Path(source)
    destination = Path(destination)
    if destination.suffix.lower() != ".webp":
        destination = destination.with_suffix(".webp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(
        destination.suffix + f".{secrets.token_hex(6)}.tmp"
    )
    edge = max(256, min(int(max_edge), 8192))
    quality = max(40, min(int(quality), 95))
    method = max(0, min(int(method), 6))
    try:
        with Image.open(source) as loaded:
            image = ImageOps.exif_transpose(loaded)
            width, height = image.size
            if width > 0 and height > 0 and max(width, height) > edge:
                image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if has_alpha else "RGB")
            elif image.mode == "RGBA" and not has_alpha:
                image = image.convert("RGB")
            image.save(
                temporary,
                format="WEBP",
                quality=quality,
                method=method,
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


class GalleryAssetStore:
    """Own originals and derived thumbnails behind one filesystem Interface."""

    def __init__(
        self,
        images_dir: Path,
        *,
        thumbnail_edge: int = 512,
        thumbnail_quality: int = 82,
        original_max_edge: int = 4096,
        original_quality: int = 85,
    ) -> None:
        self.images_dir = Path(images_dir).resolve()
        self.thumbnail_edge = max(64, min(int(thumbnail_edge), 2048))
        self.thumbnail_quality = max(40, min(int(thumbnail_quality), 95))
        self.original_max_edge = max(256, min(int(original_max_edge), 8192))
        self.original_quality = max(40, min(int(original_quality), 95))

    def publish_compressed(
        self,
        source: Path,
        destination_relative: str,
        *,
        max_edge: int | None = None,
        quality: int | None = None,
    ) -> str:
        """Write a compressed WebP under images_dir and return the relative path."""

        relative = Path(str(destination_relative).replace("\\", "/"))
        if relative.suffix.lower() != ".webp":
            relative = relative.with_suffix(".webp")
        destination = self._resolve_relative(relative.as_posix())
        compress_image_for_storage(
            Path(source),
            destination,
            max_edge=self.original_max_edge if max_edge is None else max_edge,
            quality=self.original_quality if quality is None else quality,
        )
        return relative.as_posix()

    def ensure_thumbnail(self, original_relative: str) -> str:
        original = self._resolve_relative(original_relative)
        if not original.is_file():
            raise FileNotFoundError(original)
        thumbnail_relative = Path(self.thumbnail_relative(original_relative))
        thumbnail = self._resolve_relative(thumbnail_relative.as_posix())
        if (
            thumbnail.is_file()
            and thumbnail.stat().st_mtime_ns >= original.stat().st_mtime_ns
        ):
            return thumbnail_relative.as_posix()

        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        compress_image_for_storage(
            original,
            thumbnail,
            max_edge=self.thumbnail_edge,
            quality=self.thumbnail_quality,
            method=4,
        )
        return thumbnail_relative.as_posix()

    def thumbnail_relative(self, original_relative: str) -> str:
        original = self._resolve_relative(original_relative)
        relative = Path(relative_to_canonical(original, self.images_dir))
        return (Path("_thumbs") / relative.parent / f"{relative.stem}.webp").as_posix()

    def storage_status(self, *, quota_bytes: int = 0) -> dict[str, int | bool]:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        asset_bytes = 0
        original_files = 0
        thumbnail_files = 0
        for path in self.images_dir.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            asset_bytes += path.stat().st_size
            relative = path.relative_to(self.images_dir)
            if relative.parts and relative.parts[0] == "_thumbs":
                thumbnail_files += 1
            else:
                original_files += 1
        quota = max(0, int(quota_bytes))
        remaining = max(0, quota - asset_bytes) if quota else 0
        disk_usage = shutil.disk_usage(self.images_dir)
        return {
            "asset_bytes": asset_bytes,
            "original_files": original_files,
            "thumbnail_files": thumbnail_files,
            "disk_total_bytes": disk_usage.total,
            "disk_used_bytes": disk_usage.used,
            "disk_free_bytes": disk_usage.free,
            "quota_bytes": quota,
            "quota_remaining_bytes": remaining,
            "quota_exceeded": bool(quota and asset_bytes > quota),
        }

    def has_capacity(self, additional_bytes: int, *, quota_bytes: int = 0) -> bool:
        additional = max(0, int(additional_bytes))
        status = self.storage_status(quota_bytes=quota_bytes)
        if int(status["disk_free_bytes"]) < additional:
            return False
        quota = int(status["quota_bytes"])
        return not quota or int(status["asset_bytes"]) + additional <= quota

    def reconcile(
        self,
        referenced_originals: Iterable[str],
        *,
        delete: bool = False,
        quarantine: Path | None = None,
    ) -> dict[str, int]:
        live: set[str] = set()
        for relative in referenced_originals:
            original = self._resolve_relative(relative)
            normalized = relative_to_canonical(original, self.images_dir)
            live.add(normalized)
            thumb = Path("_thumbs") / Path(normalized).parent / (
                Path(normalized).stem + ".webp"
            )
            live.add(thumb.as_posix())

        quarantine_dir: Path | None = None
        if quarantine is not None:
            candidate = Path(quarantine)
            if not candidate.is_absolute():
                candidate = self.images_dir / candidate
            resolved = canonical_path(candidate)
            if not path_is_within(resolved, self.images_dir):
                raise ValueError(
                    "quarantine directory must live under images_dir"
                )
            quarantine_dir = resolved
        orphans: list[Path] = []
        orphan_bytes = 0
        if self.images_dir.is_dir():
            for path in self.images_dir.rglob("*"):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = relative_to_canonical(path, self.images_dir)
                # Quarantined files are already handled; never re-flag them.
                if relative.split("/", 1)[0] == "_orphans":
                    continue
                if relative not in live:
                    orphans.append(path)
                    orphan_bytes += path.stat().st_size
        quarantined = 0
        if quarantine_dir is not None and orphans:
            for path in orphans:
                relative = Path(relative_to_canonical(path, self.images_dir))
                target = quarantine_dir / relative
                if not path_is_within(target, self.images_dir):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target = target.with_name(
                        f"{target.stem}.{secrets.token_hex(4)}{target.suffix}"
                    )
                try:
                    os.replace(path, target)
                    quarantined += 1
                except OSError:
                    continue
        elif delete:
            for path in orphans:
                path.unlink(missing_ok=True)
            for directory in sorted(
                (item for item in self.images_dir.rglob("*") if item.is_dir()),
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                try:
                    directory.rmdir()
                except OSError:
                    continue
        return {
            "orphan_files": len(orphans),
            "orphan_bytes": orphan_bytes,
            "deleted_files": len(orphans) if (delete and quarantine_dir is None) else 0,
            "quarantined_files": quarantined,
        }

    def _resolve_relative(self, relative: str) -> Path:
        candidate = canonical_path(self.images_dir / str(relative).replace("\\", "/"))
        if not path_is_within(candidate, self.images_dir):
            raise ValueError("gallery asset path escapes images directory")
        return candidate

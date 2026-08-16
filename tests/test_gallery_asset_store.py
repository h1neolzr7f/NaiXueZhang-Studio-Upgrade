from __future__ import annotations

from pathlib import Path

from PIL import Image

from gallery_asset_store import GalleryAssetStore


def test_gallery_asset_store_creates_bounded_webp_thumbnail(tmp_path: Path) -> None:
    images = tmp_path / "images"
    original = images / "NAI" / "7" / "11_p0.png"
    original.parent.mkdir(parents=True)
    Image.new("RGB", (1600, 900), (24, 48, 96)).save(original)

    store = GalleryAssetStore(images)
    thumbnail_relative = store.ensure_thumbnail("NAI/7/11_p0.png")

    assert thumbnail_relative == "_thumbs/NAI/7/11_p0.webp"
    thumbnail = images / thumbnail_relative
    assert thumbnail.is_file()
    with Image.open(thumbnail) as rendered:
        assert rendered.format == "WEBP"
        assert rendered.width <= 512
        assert rendered.height <= 512


def test_gallery_asset_store_reports_and_enforces_storage_quota(tmp_path: Path) -> None:
    images = tmp_path / "images"
    original = images / "NAI" / "7" / "asset.bin"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"x" * 12)
    store = GalleryAssetStore(images)

    status = store.storage_status(quota_bytes=20)

    assert status["asset_bytes"] == 12
    assert status["quota_remaining_bytes"] == 8
    assert status["quota_exceeded"] is False
    # ext4 and similar filesystems reserve blocks, so used+free can be less than total.
    assert status["disk_used_bytes"] + status["disk_free_bytes"] <= status["disk_total_bytes"]
    assert status["disk_total_bytes"] > 0
    assert store.has_capacity(8, quota_bytes=20) is True
    assert store.has_capacity(9, quota_bytes=20) is False


def test_gallery_asset_store_reconciles_orphans_without_touching_live_assets(
    tmp_path: Path,
) -> None:
    images = tmp_path / "images"
    live = images / "NAI" / "7" / "live.png"
    orphan = images / "NAI" / "7" / "orphan.png"
    live.parent.mkdir(parents=True)
    Image.new("RGB", (64, 64), (1, 2, 3)).save(live)
    Image.new("RGB", (64, 64), (4, 5, 6)).save(orphan)
    store = GalleryAssetStore(images)
    live_thumb = images / store.ensure_thumbnail("NAI/7/live.png")
    orphan_thumb = images / store.ensure_thumbnail("NAI/7/orphan.png")

    preview = store.reconcile({"NAI/7/live.png"}, delete=False)
    removed = store.reconcile({"NAI/7/live.png"}, delete=True)

    assert preview["orphan_files"] == 2
    assert preview["deleted_files"] == 0
    assert removed["deleted_files"] == 2
    assert live.is_file() and live_thumb.is_file()
    assert not orphan.exists() and not orphan_thumb.exists()

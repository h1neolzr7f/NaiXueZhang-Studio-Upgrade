from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI

import generated_gallery as gallery
import generated_layout as layout
from routes import gallery as gallery_routes
from tests.asgi_client import TestClient


def test_migrate_splits_images_and_sidecars_by_work(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    stem = "20260824_211857_148828440"
    (generated / f"{stem}.png").write_bytes(b"png")
    (generated / f"{stem}_clean.png").write_bytes(b"clean")
    (generated / f"{stem}_final.png").write_bytes(b"final")
    (generated / f"{stem}.png.meta.json").write_text(
        json.dumps(
            {
                "work_id": 148828440,
                "source_gallery_id": "aitag-online",
                "source_title": "[0824] 中野一花 | 中野二乃",
            }
        ),
        encoding="utf-8",
    )
    (generated / f"{stem}.thumb.webp").write_bytes(b"thumb")
    (generated / "20260824_120000.png").write_bytes(b"solo")

    result = layout.migrate_generated_layout(generated)

    assert result["moved"] == 6
    work = layout.find_work_dir(148828440, gallery_id="aitag-online", root=generated)
    assert work is not None
    assert (work / "images" / "原图" / f"{stem}.png").is_file()
    assert (work / "images" / "已去元数据" / f"{stem}_clean.png").is_file()
    assert (work / "images" / "已去元数据" / f"{stem}_final.png").is_file()
    assert (work / "files" / f"{stem}.png.meta.json").is_file()
    assert (work / "files" / f"{stem}.thumb.webp").is_file()
    assert not (work / "images" / f"{stem}.png.meta.json").exists()
    assert not (work / "images" / f"{stem}_final.png").exists()
    standalone = generated / "_standalone" / "images" / "原图" / "20260824_120000.png"
    assert standalone.is_file()
    assert not (generated / f"{stem}.png").exists()


def test_destination_png_reuses_existing_work_folder(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    first = layout.destination_png(
        "20260824_211800_501.png",
        root=generated,
        work_id=501,
        source_title="角色A",
        source_gallery_id="site",
    )
    first.write_bytes(b"one")
    layout.note_generated_change(generated)
    second = layout.destination_png(
        "20260824_211801_501.png",
        root=generated,
        work_id=501,
        source_title="角色A 改名",
        source_gallery_id="site",
    )
    assert first.parent == second.parent
    assert first.parent.name == "原图"
    assert first.parent.parent.name == "images"
    assert first.parent.parent.parent.name.startswith("501_")


def test_scan_and_serve_find_organized_files(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    stem = "20260824_211900_501"
    dest = layout.destination_png(
        f"{stem}.png",
        root=generated,
        work_id=501,
        source_title="测试作品",
    )
    dest.write_bytes(b"png-bytes")
    layout.note_generated_change(generated)

    with patch.object(gallery, "GENERATED_DIR", generated), patch.object(
        gallery, "_ITEMS_CACHE_FILE", tmp_path / "cache" / "items.json"
    ), patch.object(
        gallery, "_GROUPS_CACHE_FILE", tmp_path / "cache" / "groups.json"
    ):
        gallery.invalidate_scan_cache()
        gallery.register_generated(
            f"{stem}.png",
            work_id=501,
            source_title="测试作品",
        )
        items = gallery.scan_all_items(force=True)
        groups = gallery.list_groups(force=True)

    assert [item["id"] for item in items] == [stem]
    assert items[0]["image_url"] == f"/data/generated/{stem}.png"
    assert {group["group_id"] for group in groups} == {"501"}
    meta = dest.parent.parent.parent / "files" / f"{stem}.png.meta.json"
    assert meta.is_file()
    assert dest.parent.name == "原图"
    assert dest.parent.parent.name == "images"

    with patch.object(gallery_routes, "GENERATED_DIR", generated):
        app = FastAPI()
        app.include_router(gallery_routes.router)
        response = TestClient(app).get(f"/data/generated/{stem}.png")

    assert response.status_code == 200
    assert response.content == b"png-bytes"


def test_existing_work_images_split_original_and_cleaned(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    work = generated / "501_测试"
    images = work / "images"
    images.mkdir(parents=True)
    (work / "files").mkdir()
    stem = "20260825_120000_501"
    (images / f"{stem}.png").write_bytes(b"orig")
    (images / f"{stem}_clean.png").write_bytes(b"clean")
    (images / f"{stem}_final.png").write_bytes(b"final")

    result = layout.migrate_generated_layout(generated)

    assert result["moved"] >= 3
    assert (images / "原图" / f"{stem}.png").read_bytes() == b"orig"
    assert (images / "已去元数据" / f"{stem}_clean.png").read_bytes() == b"clean"
    assert (images / "已去元数据" / f"{stem}_final.png").read_bytes() == b"final"
    assert not (images / f"{stem}.png").exists()
    assert not (images / f"{stem}_final.png").exists()


def test_legacy_flat_files_still_resolve(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    png = generated / "20260824_212000_501.png"
    png.write_bytes(b"flat")
    found = layout.find_generated_file(png.name, root=generated)
    assert found == png
    assert layout.resolve_png(png.name, root=generated) == png


def test_reveal_opens_real_work_folder(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    stem = "20260824_212100_501"
    dest = layout.destination_png(
        f"{stem}.png",
        root=generated,
        work_id=501,
        source_title="揭示测试",
    )
    dest.write_bytes(b"png")
    files_dir = dest.parent.parent.parent / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (files_dir / f"{stem}.png.meta.json").write_text(
        '{"work_id": 501}',
        encoding="utf-8",
    )
    layout.note_generated_change(generated)

    with patch.object(gallery, "GENERATED_DIR", generated), patch.object(
        gallery, "_ITEMS_CACHE_FILE", tmp_path / "cache" / "items.json"
    ), patch.object(
        gallery, "_GROUPS_CACHE_FILE", tmp_path / "cache" / "groups.json"
    ), patch.object(
        gallery, "_SCAN_CACHE", {"sig": None, "items": None, "groups": None}
    ):
        paths = gallery.files_for_generated_image(stem)
        folder = gallery.reveal_target_folder(paths, f"item-{stem}")

    assert folder == dest.parent.parent.parent
    assert (folder / "images" / "原图").is_dir()
    assert (folder / "files").is_dir()

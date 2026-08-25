from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import generated_gallery as gallery
from routes import gallery as gallery_routes
from routes import nai as nai_routes


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")


def test_reveal_rejects_path_injection() -> None:
    with pytest.raises(ValueError):
        gallery.files_for_generated_image("../secret")
    with pytest.raises(ValueError):
        gallery.files_for_generated_image("..\\windows\\system32")


def test_primary_stem_strips_processed_suffixes() -> None:
    assert gallery.primary_stem("20260824_215000_final.png") == "20260824_215000"
    assert gallery.primary_stem("20260824_215000_up2x_clean") == "20260824_215000"
    assert gallery.primary_stem("20260824_215000_1.png.meta.json") == "20260824_215000_1"


def test_stage_reveal_folder_only_exposes_requested_names(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    reveal = tmp_path / "cache" / "reveal"
    stem = "20260824_215000"
    original = generated / f"{stem}.png"
    processed = generated / f"{stem}_final.png"
    other = generated / "20260824_000000.png"
    _write_png(original)
    _write_png(processed)
    _write_png(other)

    with patch.object(gallery, "GENERATED_DIR", generated), patch.object(
        gallery, "_REVEAL_DIR", reveal
    ):
        paths = gallery.files_for_generated_image(stem)
        folder = gallery.stage_reveal_folder(paths, f"item-{stem}")

    names = {path.name for path in folder.rglob("*") if path.is_file()}
    assert f"{stem}.png" in names
    assert f"{stem}_final.png" in names
    assert "20260824_000000.png" not in names
    assert (folder / "images" / f"{stem}.png").is_file()
    assert str(tmp_path) not in folder.name


def test_group_reveal_collects_every_original_in_the_group(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    first = generated / "20260824_215000.png"
    second = generated / "20260824_215100.png"
    _write_png(first)
    _write_png(second)
    first.with_suffix(first.suffix + ".meta.json").write_text(
        '{"work_id": 42, "source_gallery_id": "site"}',
        encoding="utf-8",
    )
    second.with_suffix(second.suffix + ".meta.json").write_text(
        '{"work_id": 42, "source_gallery_id": "site"}',
        encoding="utf-8",
    )

    with patch.object(gallery, "GENERATED_DIR", generated), patch.object(
        gallery, "_SCAN_CACHE", {"sig": None, "items": None, "groups": None}
    ):
        paths = gallery.files_for_generated_group("42")

    names = {path.name for path in paths}
    assert "20260824_215000.png" in names
    assert "20260824_215100.png" in names


def test_reveal_routes_never_leak_absolute_paths(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    reveal = tmp_path / "cache" / "reveal"
    stem = "20260824_215000"
    png = generated / f"{stem}.png"
    _write_png(png)

    with patch.object(gallery, "GENERATED_DIR", generated), patch.object(
        gallery, "_REVEAL_DIR", reveal
    ), patch.object(gallery, "open_local_folder", return_value=False):
        item = gallery_routes.api_generated_reveal(stem)

    assert item["ok"] is True
    assert item["opened"] is False
    assert str(tmp_path) not in str(item)
    assert item["files"] == [f"{stem}.png"]

    staged = reveal / "group-42"
    staged.mkdir(parents=True)
    with patch.object(nai_routes, "files_for_generated_group", return_value=[png]), patch.object(
        nai_routes, "reveal_target_folder", return_value=staged
    ), patch.object(nai_routes, "open_local_folder", return_value=False):
        result = nai_routes.api_generated_reveal_group("42")

    assert result["ok"] is True
    assert result["opened"] is False
    assert str(tmp_path) not in str(result)
    assert result["files"] == [f"{stem}.png"]


def test_work_files_ignore_paths_outside_data_dir(tmp_path: Path) -> None:
    from gallery_audit_service import files_for_work_images

    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    db = type(
        "DB",
        (),
        {
            "get_work_detail": staticmethod(
                lambda _id: {"images": [{"local_path": str(outside), "page_index": 0}]}
            )
        },
    )()
    with patch("gallery_audit_service.DB", db):
        with pytest.raises(FileNotFoundError):
            files_for_work_images(7, "site")


def test_work_reveal_route_never_leaks_absolute_paths(tmp_path: Path) -> None:
    image = tmp_path / "p0.webp"
    image.write_bytes(b"webp")
    staged = tmp_path / "reveal-work"
    staged.mkdir()
    (staged / "p0.webp").write_bytes(b"webp")
    with patch(
        "gallery_audit_service.files_for_work_images", return_value=[image]
    ), patch(
        "generated_gallery.stage_reveal_folder", return_value=staged
    ), patch(
        "generated_gallery.open_local_folder", return_value=False
    ), patch.object(
        gallery_routes, "_work_scope_guard", return_value=None
    ):
        result = gallery_routes.api_work_reveal(7, "site")

    assert result["ok"] is True
    assert result["files"] == ["p0.webp"]
    assert str(tmp_path) not in str(result)
    assert "count" in result

from __future__ import annotations

import asyncio
import io
import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from db import Database
from routes import gallery as gallery_routes


def _nai_png_bytes(prompt: str = "1girl") -> bytes:
    buf = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Software", "NovelAI")
    metadata.add_text("Source", "NovelAI Diffusion V4.5")
    metadata.add_text("Description", prompt)
    metadata.add_text("Comment", json.dumps({"prompt": prompt}))
    Image.new("RGB", (8, 8)).save(buf, format="PNG", pnginfo=metadata)
    return buf.getvalue()


def _plain_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    return buf.getvalue()


class _FakeUpload:
    def __init__(self, name: str, data: bytes) -> None:
        self.filename = name
        self._data = data

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._data
        return self._data[:size]


def _patched_env(tmp_path: Path, gallery_id: str):
    spec = gallery_routes.get_gallery_spec(gallery_id)
    tmp_spec = type(spec)(
        id=spec.id,
        label_zh=spec.label_zh,
        label_en=spec.label_en,
        description_zh=spec.description_zh,
        description_en=spec.description_en,
        db_path=tmp_path / "gallery.db",
        images_dir=tmp_path / "images",
        asset_base_url="/data/gallery/codex/",
        cdn_fallback=False,
        local_scope="",
        group_by=spec.group_by,
    )
    tmp_db = Database(tmp_spec.db_path)
    patchers = (
        patch.object(gallery_routes, "get_gallery_spec", return_value=tmp_spec),
        patch.object(gallery_routes, "get_gallery_db", return_value=tmp_db),
        patch("scripts.gallery_import_common.get_db", return_value=tmp_db),
        patch("scripts.gallery_import_common.ensure_gallery_dirs", side_effect=lambda _gid: None),
        patch("gallery_catalog.get_db", return_value=tmp_db),
        patch("gallery_catalog.get_spec", return_value=tmp_spec),
    )
    return patchers, tmp_spec, tmp_db


@contextmanager
def _active(patchers):
    with ExitStack() as stack:
        for item in patchers:
            stack.enter_context(item)
        yield


def test_drop_import_accepts_nai_image_and_stores_category(tmp_path: Path) -> None:
    patchers, spec, db = _patched_env(tmp_path, "codex")
    with _active(patchers):
        result = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="角色/阿米娅",
                files=[_FakeUpload("amy.png", _nai_png_bytes())],
            )
        )
    assert result["ok"] is True
    assert len(result["accepted"]) == 1
    assert result["accepted"][0]["category"] == "角色/阿米娅"
    assert result["rejected"] == []
    works = db.search_works(page_size=20)
    assert len(works["items"]) == 1
    stored = works["items"][0]
    assert stored["category"] == "角色/阿米娅"
    assert stored["group_key"] == "角色/阿米娅"
    assert list((spec.images_dir).rglob("*.png"))
    found = db.search_works(group="group:角色/阿米娅", page_size=20)
    assert len(found["items"]) == 1


def test_drop_import_rejects_plain_image(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    with _active(patchers):
        result = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="未分类",
                files=[_FakeUpload("plain.png", _plain_png_bytes())],
            )
        )
    assert result["accepted"] == []
    assert result["rejected"][0]["reason"] == "nai_metadata_missing"
    assert db.search_works(page_size=20)["items"] == []


def test_drop_import_rejects_site_gallery(tmp_path: Path) -> None:
    from fastapi import HTTPException

    try:
        asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "site",
                category="x",
                files=[_FakeUpload("a.png", _nai_png_bytes())],
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("site gallery must reject import-drop")


def test_drop_import_is_idempotent_for_same_image(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    data = _nai_png_bytes()
    with _active(patchers):
        first = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex", category="画集", files=[_FakeUpload("a.png", data)]
            )
        )
        second = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex", category="画集", files=[_FakeUpload("a.png", data)]
            )
        )
    assert first["accepted"] and second["accepted"]
    assert len(db.search_works(page_size=20)["items"]) == 1


def test_redrop_same_image_keeps_the_original_auto_folder(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    data = _nai_png_bytes("same-night")
    with _active(patchers):
        first = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="",
                files=[_FakeUpload("night.png", data)],
            )
        )
        second = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="",
                files=[_FakeUpload("night-again.png", data)],
            )
        )
        folders = gallery_routes.list_group_keys("codex")
    assert first["folder"] == second["folder"]
    assert second["accepted"][0]["existing"] is True
    assert len(db.search_works(page_size=20)["items"]) == 1
    assert [item["group_key"] for item in folders] == [first["folder"]]


def test_empty_category_creates_a_drop_folder(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    with _active(patchers):
        first = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="",
                files=[_FakeUpload("night.png", _nai_png_bytes("night"))],
            )
        )
        second = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="",
                files=[_FakeUpload("day.png", _nai_png_bytes("day"))],
            )
        )
        folders = gallery_routes.list_group_keys("codex")
    assert first["folder"].startswith("拖入 ")
    assert second["folder"].startswith("拖入 ")
    assert first["folder"] != second["folder"]
    stored = db.search_works(page_size=20)["items"]
    assert {item["group_key"] for item in stored} == {first["folder"], second["folder"]}
    assert {item["kind"] for item in folders} == {"folder"}
    assert {item["group_key"] for item in folders} == {first["folder"], second["folder"]}


def test_qqgroup_drop_uses_the_same_folder_identity(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "qqgroup")
    with _active(patchers):
        result = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "qqgroup",
                category="群收藏",
                files=[_FakeUpload("qq.png", _nai_png_bytes())],
            )
        )
        folders = gallery_routes.list_group_keys("qqgroup")
    assert result["folder"] == "群收藏"
    stored = db.search_works(page_size=20)["items"][0]
    assert stored["group_key"] == "群收藏"
    assert stored["account_key"] == "local-drop"
    assert folders[0]["kind"] == "folder"
    assert folders[0]["group_key"] == "群收藏"


def test_merge_folders_moves_works_into_the_target(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    with _active(patchers):
        asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="批次甲",
                files=[_FakeUpload("a.png", _nai_png_bytes("girl a"))],
            )
        )
        asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="批次乙",
                files=[_FakeUpload("b.png", _nai_png_bytes("girl b"))],
            )
        )
        result = asyncio.run(
            gallery_routes.api_gallery_merge_folders(
                "codex",
                {"source_keys": ["批次甲"], "target_key": "批次乙"},
            )
        )
        leftover = gallery_routes.list_group_keys("codex")
    moved = db.search_works(group="group:批次乙", page_size=20)["items"]
    assert result["moved"] == 1
    assert len(moved) == 2
    assert db.search_works(group="group:批次甲", page_size=20)["items"] == []
    assert [item["group_key"] for item in leftover] == ["批次乙"]
    detail = db.get_work_detail(moved[0]["id"])
    assert detail is not None
    assert detail["work"]["group_key"] == "批次乙"
    assert detail["work"]["category"] == "批次乙"


def test_merge_folders_rejects_site_gallery() -> None:
    from fastapi import HTTPException

    try:
        asyncio.run(
            gallery_routes.api_gallery_merge_folders(
                "site",
                {"source_keys": ["a"], "target_key": "b"},
            )
        )
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("site gallery must reject folder merge")


def test_redrop_keeps_original_create_date(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    data = _nai_png_bytes("dated")
    dates = iter(["2026-01-01T00:00:00Z", "2026-08-14T12:00:00Z"])
    with _active(patchers), patch(
        "scripts.gallery_import_common.now_iso",
        side_effect=lambda: next(dates),
    ):
        asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="画集",
                files=[_FakeUpload("a.png", data)],
            )
        )
        asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="画集",
                files=[_FakeUpload("b.png", data)],
            )
        )
    row = db._run(lambda: db.conn.execute("SELECT create_date, list_json FROM works").fetchone())
    assert row["create_date"] == "2026-01-01T00:00:00Z"
    stored = json.loads(row["list_json"])
    assert stored["create_date"] == "2026-01-01T00:00:00Z"


def test_merge_ignores_qq_works_that_only_share_group_label(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "qqgroup")
    with _active(patchers):
        asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "qqgroup",
                category="同人图",
                files=[_FakeUpload("drop.png", _nai_png_bytes("drop"))],
            )
        )

        def insert_crawled() -> None:
            crawled = {
                "id": 987001,
                "title": "crawled",
                "group_key": "987",
                "group_label": "同人图",
                "account_key": "qq-user",
                "account_label": "某账号",
            }
            db.conn.execute(
                "INSERT INTO works(id, title, caption, tags, ai_type, create_date, image_count, list_json) "
                "VALUES (?, ?, ?, ?, 'NAI', ?, 1, ?)",
                (
                    987001,
                    "crawled",
                    "来自 同人图 / 某账号",
                    "qqgroup,NAI,group:987",
                    "2026-01-01T00:00:00Z",
                    json.dumps(crawled, ensure_ascii=False),
                ),
            )
            db.conn.commit()

        db._run(insert_crawled)
        result = asyncio.run(
            gallery_routes.api_gallery_merge_folders(
                "qqgroup",
                {"source_keys": ["同人图"], "target_key": "合集"},
            )
        )
    assert result["moved"] == 1
    moved = db.search_works(group="group:合集", page_size=20)["items"]
    stayed = db.search_works(group="group:987", page_size=20)["items"]
    assert len(moved) == 1
    assert moved[0]["group_key"] == "合集"
    assert len(stayed) == 1
    assert stayed[0]["group_key"] == "987"
    assert stayed[0]["group_label"] == "同人图"


def test_drop_import_rejects_when_batch_exceeds_total_bytes(tmp_path: Path) -> None:
    patchers, _spec, db = _patched_env(tmp_path, "codex")
    with _active(patchers), patch.object(gallery_routes, "_DROP_MAX_TOTAL_BYTES", 1):
        result = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="x",
                files=[_FakeUpload("a.png", _nai_png_bytes())],
            )
        )
    assert result["accepted"] == []
    assert result["rejected"][0]["reason"] == "batch_too_large"
    assert db.search_works(page_size=20)["items"] == []

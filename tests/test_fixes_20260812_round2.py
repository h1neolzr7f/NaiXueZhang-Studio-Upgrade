"""Regression tests for the 2026-08-12 second-round audit fixes.

Covers: token masking, CDN redirect policy, local_path root convention,
conditional permanence of thumbnail_requires_p0_nai, WebP migration
detail_json rewrite, multi-page draft cover identity, release backup-dir
filtering, and extensionless image URL probing.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image, PngImagePlugin

import nai_api
from paths import normalize_image_relative
from routes import gallery as gallery_routes
from tests.asgi_client import TestClient


# --- token masking -----------------------------------------------------------


def test_mask_token_never_reveals_tail() -> None:
    token = "pst-0123456789abcdefSECRETTAIL"
    masked = nai_api._mask_token(token)
    assert masked.startswith("pst-")
    assert token[-6:] not in masked
    assert token[6:] not in masked  # 除类型前缀外不回显任何连续片段
    assert nai_api._mask_token("short") == "*****"
    assert nai_api._mask_token("") == ""


def test_public_token_entry_hides_network_layout() -> None:
    entry = {
        "id": "nai_abc",
        "label": "main",
        "provider": "novelai",
        "enabled": True,
        "masked": "pst-********",
        "updated_at": "2026-08-12",
        "api_base": "https://internal-proxy.lan:8443/v1",
        "proxy": "http://192.168.1.10:7890",
        "disabled_at": "",
        "disabled_reason": "",
    }
    public = nai_api._public_token_entry(entry)
    assert public["api_base"] == ""
    assert public["proxy"] == ""
    assert public["has_api_base"] is True
    assert public["has_proxy"] is True
    assert "192.168.1.10" not in json.dumps(public)
    assert "internal-proxy.lan" not in json.dumps(public)


# --- CDN redirect policy -----------------------------------------------------


def test_cdn_client_does_not_follow_redirects() -> None:
    import server_shared

    assert server_shared._CDN_CLIENT.follow_redirects is False


def test_cdn_3xx_is_treated_as_soft_miss(tmp_path: Path) -> None:
    http = Mock()
    http.get.return_value = httpx.Response(
        302, headers={"location": "http://169.254.169.254/latest/meta-data"}
    )
    gallery_routes._CDN_MISS_CACHE.clear()
    with patch.object(gallery_routes, "DATA_DIR", tmp_path), patch.object(
        gallery_routes, "CDN_URL", "https://cdn.example.test/base"
    ), patch.object(gallery_routes, "_CDN_CLIENT", http):
        app = FastAPI()
        app.include_router(gallery_routes.router)
        response = TestClient(app).get("/data/images/NAI/1/redirected.webp")

    assert response.status_code == 404
    assert b"169.254.169.254" not in response.content


# --- local_path root convention ----------------------------------------------


def test_normalize_image_relative_unifies_root_conventions() -> None:
    assert normalize_image_relative("NAI/7/a.webp") == "NAI/7/a.webp"
    assert normalize_image_relative("images/NAI/7/a.webp") == "NAI/7/a.webp"
    assert normalize_image_relative("data/images/NAI/7/a.webp") == "NAI/7/a.webp"
    assert normalize_image_relative("\\images\\NAI\\7\\a.webp") == "NAI/7/a.webp"
    assert normalize_image_relative("") == ""
    assert normalize_image_relative(None) == ""


# --- thumbnail_requires_p0_nai conditional permanence -------------------------


def _write_nai_png(path: Path, prompt: str = "1girl", seed: int = 1) -> None:
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("Software", "NovelAI")
    png_info.add_text("Source", "NovelAI Diffusion V4.5")
    png_info.add_text("Description", prompt)
    png_info.add_text(
        "Comment",
        json.dumps({"prompt": prompt, "seed": seed}, ensure_ascii=False),
    )
    Image.new("RGB", (64, 96), (32, 48, 64)).save(path, pnginfo=png_info)


def _make_intake(tmp_path: Path, name: str = "gallery.db"):
    from db import Database
    from pixiv_nai_intake import PixivNAIIntake

    db = Database(tmp_path / name)
    intake = PixivNAIIntake(
        db=db,
        images_dir=tmp_path / "images",
        staging_dir=tmp_path / "staging",
        allowed_image_hosts=("i.pximg.test",),
        thumbnail_only_pages=True,
    )
    return db, intake


def _make_work(work_id: int = 700) -> "object":
    from pixiv_nai_intake import PixivPage, PixivWork

    return PixivWork(
        work_id=work_id,
        user_id=70,
        user_name="CoverTester",
        title="cover gate",
        caption="",
        tags=("NovelAI",),
        create_date="2026-08-12T00:00:00+00:00",
        total_view=1,
        total_bookmarks=1,
        pages=(
            PixivPage(0, f"https://i.pximg.test/{work_id}_p0.png"),
            PixivPage(
                1,
                f"https://i.pximg.test/{work_id}_p1.png",
                thumbnail_url=f"https://i.pximg.test/{work_id}_p1_thumb.jpg",
            ),
            PixivPage(
                2,
                f"https://i.pximg.test/{work_id}_p2.png",
                thumbnail_url=f"https://i.pximg.test/{work_id}_p2_thumb.jpg",
            ),
        ),
    )


def test_thumbnail_reject_is_permanent_when_p0_permanently_rejected(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    plain = sources / "plain.png"
    thumb = sources / "thumb.jpg"
    Image.new("RGB", (64, 96), (1, 2, 3)).save(plain)
    Image.new("RGB", (32, 48), (4, 5, 6)).save(thumb)
    source_by_url = {
        "https://i.pximg.test/700_p0.png": plain,
        "https://i.pximg.test/700_p1_thumb.jpg": thumb,
        "https://i.pximg.test/700_p2_thumb.jpg": thumb,
    }
    calls: list[str] = []

    def download(url: str, destination: Path) -> None:
        calls.append(url)
        shutil.copy2(source_by_url[url], destination)

    db, intake = _make_intake(tmp_path)
    work = _make_work(700)
    try:
        first = intake.ingest_work(work, download)
        assert [page.status for page in first.pages] == [
            "rejected",
            "rejected",
            "rejected",
        ]
        assert first.pages[0].reason == "nai_metadata_missing"
        assert [page.reason for page in first.pages[1:]] == [
            "thumbnail_requires_p0_nai",
            "thumbnail_requires_p0_nai",
        ]
        assert db.get_work_detail(700) is None

        second = intake.ingest_work(work, download)
    finally:
        db.close()

    # 整作永久跳过：封面非 NAI 时后续缩略页不再重复打 CDN。
    assert second.status == "unchanged"
    assert len(calls) == 3


def test_thumbnail_reject_retries_when_p0_failure_was_temporary(
    tmp_path: Path,
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    nai = sources / "nai.png"
    thumb = sources / "thumb.jpg"
    _write_nai_png(nai, prompt="1girl, cover", seed=9)
    Image.new("RGB", (32, 48), (7, 8, 9)).save(thumb)
    source_by_url = {
        "https://i.pximg.test/701_p0.png": nai,
        "https://i.pximg.test/701_p1_thumb.jpg": thumb,
        "https://i.pximg.test/701_p2_thumb.jpg": thumb,
    }
    calls: list[str] = []
    fail_p0 = True

    def download(url: str, destination: Path) -> None:
        calls.append(url)
        if fail_p0 and url.endswith("_p0.png"):
            raise OSError("simulated network blip")
        shutil.copy2(source_by_url[url], destination)

    db, intake = _make_intake(tmp_path)
    work = _make_work(701)
    try:
        first = intake.ingest_work(work, download)
        assert first.pages[0].status == "failed"
        assert first.pages[0].reason == "download_error"
        assert [page.reason for page in first.pages[1:]] == [
            "thumbnail_requires_p0_nai",
            "thumbnail_requires_p0_nai",
        ]

        # p0 恢复可下载后重抓：派生拒绝不得被当作永久拒绝跳过。
        fail_p0 = False
        second = intake.ingest_work(work, download)
        detail = db.get_work_detail(701)
    finally:
        db.close()

    assert second.status in {"accepted", "partial", "updated"}
    assert detail is not None
    assert len(detail["images"]) == 3
    assert detail["images"][0]["image_type"] == "NAI"
    assert "https://i.pximg.test/701_p1_thumb.jpg" in calls[3:]


# --- WebP migration rewrites detail_json --------------------------------------


def test_migrate_originals_to_webp_rewrites_detail_json(tmp_path: Path) -> None:
    from db_compression import compress_text
    from gallery_maintenance import GalleryMaintenance

    data = tmp_path / "data"
    images = data / "images" / "NAI" / "1"
    images.mkdir(parents=True)
    legacy = images / "legacy.png"
    Image.new("RGB", (120, 160), (20, 40, 60)).save(legacy)
    db_path = data / "aitag.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE works(
          id INTEGER PRIMARY KEY, preview_path TEXT, preview_downloaded INTEGER,
          detail_json BLOB
        );
        CREATE TABLE work_images(
          work_id INTEGER, page_index INTEGER, local_path TEXT, image_path TEXT,
          file_name TEXT, source_sha256 TEXT, source_page_index INTEGER,
          downloaded INTEGER
        );
        CREATE TABLE pixiv_nai_receipts(
          work_id INTEGER, display_page_index INTEGER, local_path TEXT,
          source_sha256 TEXT
        );
        """
    )
    detail = {
        "work": {"id": 1, "title": "legacy"},
        "images": [
            {
                "page_index": 0,
                "local_path": "images/NAI/1/legacy.png",
                "image_path": "NAI/1/legacy.png",
                "file_name": "legacy.png",
            }
        ],
    }
    conn.execute(
        "INSERT INTO works(id, preview_path, preview_downloaded, detail_json) "
        "VALUES (1, ?, 1, ?)",
        ("images/NAI/1/legacy.png", compress_text(json.dumps(detail))),
    )
    conn.execute(
        "INSERT INTO work_images(work_id, page_index, local_path, image_path, "
        "file_name, source_sha256, source_page_index, downloaded) "
        "VALUES (1,0,?,?,?,'abc',0,1)",
        ("NAI/1/legacy.png", "NAI/1/legacy.png", "legacy.png"),
    )
    conn.commit()
    conn.close()

    result = GalleryMaintenance(data).migrate_originals_to_webp(dry_run=False)
    assert result["migrated"] == 1
    assert result["detail_rewritten"] == 1

    from db_compression import decompress_if_needed

    conn = sqlite3.connect(db_path)
    raw = conn.execute("SELECT detail_json FROM works WHERE id=1").fetchone()[0]
    conn.close()
    stored = json.loads(decompress_if_needed(raw))
    image = stored["images"][0]
    # 前缀风格保留，仅后缀目标改写为迁移后的 .webp
    assert image["local_path"] == "images/NAI/1/legacy.webp"
    assert image["image_path"] == "NAI/1/legacy.webp"
    assert image["file_name"] == "legacy.webp"


# --- multi-page draft cover identity ------------------------------------------


def test_compile_drafts_top_level_identity_prefers_cover_page() -> None:
    import aitag_core.studio as studio

    detail = SimpleNamespace(images=[object(), object(), object()])

    def fake_compile(detail_arg, *, image_index: int, **kwargs):
        if image_index == 0:
            raise ValueError("cover has no NAI metadata")
        return {"image_index": image_index, "marker": f"p{image_index}"}

    with patch.object(studio, "compile_aitag_studio_draft", fake_compile):
        result = studio.compile_aitag_studio_drafts(detail, image_indexes=[0, 1, 2])
    # 封面编译失败时才回退到第一成功页
    assert result["image_index"] == 1
    assert result["marker"] == "p1"
    assert result["partial"] is True

    def fake_compile_all(detail_arg, *, image_index: int, **kwargs):
        return {"image_index": image_index, "marker": f"p{image_index}"}

    with patch.object(studio, "compile_aitag_studio_draft", fake_compile_all):
        reordered = studio.compile_aitag_studio_drafts(detail, image_indexes=[2, 0, 1])
    # 封面参与编译时，顶层身份必须是封面页，与请求顺序无关
    assert reordered["image_index"] == 0
    assert reordered["marker"] == "p0"


# --- release backup filtering --------------------------------------------------


def test_zip_release_skips_backup_directories_and_files(tmp_path: Path) -> None:
    from scripts.zip_release import iter_files

    source = tmp_path / "src"
    (source / "web").mkdir(parents=True)
    (source / "web" / "app.js").write_text("public", encoding="utf-8")
    (source / "web" / "app.js.bak-20260811").write_text("old", encoding="utf-8")
    backup_dir = source / "web.backup-20260811"
    backup_dir.mkdir()
    (backup_dir / "app.js").write_text("old dir copy", encoding="utf-8")
    logs = source / "scripts" / "logs"
    logs.mkdir(parents=True)
    (logs / "run.log").write_text("diag", encoding="utf-8")
    (source / "data" / "images").mkdir(parents=True)
    (source / "data" / "images" / "x.webp").write_bytes(b"img")

    yielded = sorted(
        path.relative_to(source).as_posix() for path in iter_files(source)
    )
    assert yielded == ["web/app.js"]


def test_verify_release_stage_flags_backup_directory_contents(tmp_path: Path) -> None:
    from scripts.verify_release_stage import BACKUP_NAME_RE

    # 与 verify() 内一致的判定：路径任一段命中备份命名即违规
    stage = tmp_path / "stage"
    nested = stage / "web.backup-20260811"
    nested.mkdir(parents=True)
    leaked = nested / "app.js"
    leaked.write_text("copy", encoding="utf-8")
    offenders = [
        path
        for path in stage.rglob("*")
        if path.is_file()
        and any(
            BACKUP_NAME_RE.search(part)
            for part in path.relative_to(stage).parts
        )
    ]
    assert offenders == [leaked]


# --- extensionless image URL probing -------------------------------------------


def test_serve_image_probes_extensions_for_extensionless_request(
    tmp_path: Path,
) -> None:
    image = tmp_path / "images" / "NAI" / "7" / "1001_p0.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png-bytes")

    with patch.object(gallery_routes, "DATA_DIR", tmp_path), patch.object(
        gallery_routes, "CDN_URL", ""
    ):
        app = FastAPI()
        app.include_router(gallery_routes.router)
        response = TestClient(app).get("/data/images/NAI/7/1001_p0")

    assert response.status_code == 200
    assert response.content == b"png-bytes"


def test_serve_generated_probes_sibling_extensions(tmp_path: Path) -> None:
    generated = tmp_path / "gen"
    generated.mkdir()
    (generated / "abc123.webp").write_bytes(b"webp-gen")

    with patch.object(gallery_routes, "GENERATED_DIR", generated):
        app = FastAPI()
        app.include_router(gallery_routes.router)
        response = TestClient(app).get("/data/generated/abc123.png")

    assert response.status_code == 200
    assert response.content == b"webp-gen"


# --- image cache headers -------------------------------------------------------


def test_gallery_images_serve_with_day_cache(tmp_path: Path) -> None:
    image = tmp_path / "images" / "NAI" / "7" / "1001_p0.webp"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"webp-bytes")

    with patch.object(gallery_routes, "DATA_DIR", tmp_path), patch.object(
        gallery_routes, "CDN_URL", ""
    ):
        app = FastAPI()
        app.include_router(gallery_routes.router)
        response = TestClient(app).get("/data/images/NAI/7/1001_p0.webp")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=86400"


def test_generated_images_serve_with_short_cache(tmp_path: Path) -> None:
    generated = tmp_path / "gen"
    generated.mkdir()
    (generated / "abc123.png").write_bytes(b"png-gen")

    with patch.object(gallery_routes, "GENERATED_DIR", generated):
        app = FastAPI()
        app.include_router(gallery_routes.router)
        response = TestClient(app).get("/data/generated/abc123.png")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, max-age=300"


# --- import-drop atomic write ---------------------------------------------------


def test_import_drop_writes_via_atomic_primitive() -> None:
    source = (Path(gallery_routes.__file__)).read_text(encoding="utf-8")
    helper_start = source.index("def _import_drop_files")
    helper_end = source.index("async def api_gallery_import_drop", helper_start)
    helper = source[helper_start:helper_end]
    assert "atomic_write_bytes(dest, data)" in helper
    assert "dest.write_bytes" not in helper
    assert "asyncio.to_thread" in source

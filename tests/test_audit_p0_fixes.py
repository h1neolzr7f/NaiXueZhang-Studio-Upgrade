"""Regression tests for 2026-08-12 full-code audit P0 fixes."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from db_queries import ARK_MATCH_SQL
from generated_gallery import _group_key
from nai_api import _record_token_failure
from nai_char import clean_plain_ark_workbench_draft
from nai_char_modules.generation import _infer_model, build_generate_payload
from routes import gallery as gallery_routes


def _nai_png_bytes() -> bytes:
    buf = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Software", "NovelAI")
    metadata.add_text("Source", "NovelAI Diffusion V4.5")
    metadata.add_text("Description", "1girl")
    metadata.add_text("Comment", json.dumps({"prompt": "1girl"}))
    Image.new("RGB", (8, 8)).save(buf, format="PNG", pnginfo=metadata)
    return buf.getvalue()


class _FakeUpload:
    def __init__(self, name: str, data: bytes) -> None:
        self.filename = name
        self._data = data

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._data
        return self._data[:size]


def test_ark_match_sql_has_readable_literals() -> None:
    assert "明日方舟" in ARK_MATCH_SQL
    assert "arknights" in ARK_MATCH_SQL
    assert "アークナイツ" in ARK_MATCH_SQL
    assert "鏄庢棩" not in ARK_MATCH_SQL


def test_group_key_prefixes_non_site_galleries() -> None:
    assert _group_key(42, source_gallery_id="site") == "42"
    assert _group_key(42, source_gallery_id="aitag-online") == "gallery:aitag-online:42"
    assert (
        _group_key(None, source_gallery_id="codex", generation_series_id="abc")
        == "gallery:codex:run:abc:standalone"
    )


def test_token_failure_ignores_payload_validation_500() -> None:
    entry = {"id": "t-unmarshal", "provider": "novelai", "enabled": True, "token": "x"}
    removed = _record_token_failure(
        entry,
        'NAI API error 500: {"statusCode":500,"message":"json: cannot unmarshal object into Go struct field V4ExternalCharacterCaption.parameters.v4_prompt.caption.char_captions.char_caption of type string"}',
    )
    assert removed is False


def test_token_failure_does_not_remove_on_bare_400_substring() -> None:
    entry = {"id": "t1", "provider": "novelai", "enabled": True, "token": "x"}
    removed = _record_token_failure(entry, "HTTP 400: width must be multiple of 64 (got 400)")
    # Parameter-style 400 must not hard-delete the token (no auth phrase).
    assert removed is False


def test_token_failure_removes_on_recaptcha_trial_400() -> None:
    entry = {"id": "t1b", "provider": "novelai", "enabled": True, "token": "x"}
    with patch("nai_api._remove_token_entry", return_value=True) as rem:
        removed = _record_token_failure(
            entry,
            'NAI API error 400: {"message":"Recaptcha token is required for trial generation"}',
        )
    assert removed is True
    rem.assert_called_once()


def test_token_failure_removes_on_invalid_phrase() -> None:
    entry = {"id": "t2", "provider": "novelai", "enabled": True, "token": "y"}
    # Use a disposable pool entry path via monkeypatch is heavy; just check phrase match returns True
    # when remove is attempted — _remove_token_entry may no-op if not in file.
    with patch("nai_api._remove_token_entry", return_value=True) as rem:
        removed = _record_token_failure(entry, "Token invalid or expired")
    assert removed is True
    rem.assert_called_once()


def test_clean_plain_skips_aitag_online() -> None:
    comment = {
        "prompt": "1girl, amiya (arknights), long hair",
        "v4_prompt": {
            "caption": {
                "base_caption": "1girl, amiya (arknights), long hair",
                "char_captions": [{"char_caption": "1girl, silver hair"}],
            }
        },
    }
    out = clean_plain_ark_workbench_draft(
        comment, work_id=12345, page_index=0, gallery_id="aitag-online"
    )
    assert out is comment  # unchanged skip


def test_infer_model_prefers_explicit_and_defaults_to_45() -> None:
    assert _infer_model("", "nai-diffusion-4-5-full") == "nai-diffusion-4-5-full"
    assert _infer_model("NovelAI Diffusion V4.5", "") == "nai-diffusion-4-5-full"
    assert _infer_model("NovelAI Diffusion V4", "") == "nai-diffusion-4-full"
    assert _infer_model("", "") == "nai-diffusion-4-5-full"
    payload = build_generate_payload(
        {
            "model": "nai-diffusion-4-5-full",
            "prompt": "1girl",
            "width": 832,
            "height": 1216,
            "steps": 28,
        },
        force_free=True,
    )
    assert payload["model"] == "nai-diffusion-4-5-full"


def test_import_drop_rejects_dotdot_category(tmp_path: Path) -> None:
    from db import Database

    spec = gallery_routes.get_gallery_spec("codex")
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
    images_root = tmp_spec.images_dir.resolve()
    images_root.mkdir(parents=True, exist_ok=True)
    with (
        patch.object(gallery_routes, "get_gallery_spec", return_value=tmp_spec),
        patch.object(gallery_routes, "get_gallery_db", return_value=tmp_db),
        patch("scripts.gallery_import_common.get_db", return_value=tmp_db),
        patch(
            "scripts.gallery_import_common.ensure_gallery_dirs",
            side_effect=lambda _gid: None,
        ),
    ):
        result = asyncio.run(
            gallery_routes.api_gallery_import_drop(
                "codex",
                category="..",
                files=[_FakeUpload("a.png", _nai_png_bytes())],
            )
        )
    assert result["ok"] is True
    assert len(result["accepted"]) == 1
    # File must land under images_dir, never parent.
    written = list(images_root.rglob("*.png"))
    assert written
    for path in written:
        assert images_root in path.resolve().parents or path.resolve().parent == images_root
    # Parent of images_dir must not contain the drop file
    parent_hits = [
        p
        for p in tmp_path.iterdir()
        if p.is_file() and p.suffix.lower() == ".png"
    ]
    assert parent_hits == []

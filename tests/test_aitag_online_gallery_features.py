from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import favorites
from aitag_core.external import normalize_aitag_config, normalize_aitag_search
from routes import aitag as aitag_routes


class _FilterClient:
    def search(self, **kwargs):
        return normalize_aitag_search(
            {
                "items": [
                    {
                        "id": "match-1",
                        "title": "Alice at night",
                        "userName": "Alice",
                        "AI_type": "NAI",
                        "tags": ["cat", "night"],
                        "images": [
                            {"id": "m1-p0", "model": "NovelAI Diffusion V4.5"},
                            {"id": "m1-p1", "model": "NovelAI Diffusion V4.5"},
                        ],
                    },
                    {
                        "id": "wrong-creator",
                        "title": "Bob at night",
                        "userName": "Bob",
                        "AI_type": "NAI",
                        "tags": ["cat", "night"],
                        "images": [{"id": "b-p0", "model": "NovelAI Diffusion V4.5"}],
                    },
                    {
                        "id": "wrong-model",
                        "title": "Alice old model",
                        "userName": "Alice",
                        "AI_type": "NAI",
                        "tags": ["cat", "night"],
                        "images": [
                            {"id": "o-p0", "model": "NovelAI Diffusion V3"},
                            {"id": "o-p1", "model": "NovelAI Diffusion V3"},
                        ],
                    },
                ],
                "total": 3,
            },
            page=1,
            page_size=60,
        )

    def get_config(self):
        return normalize_aitag_config(
            {"asset_base_url": "https://ai-img.10118899.xyz/"}
        )


def test_online_search_supports_explicit_advanced_filters() -> None:
    with patch.object(aitag_routes, "get_aitag_client", return_value=_FilterClient()):
        result = aitag_routes.api_aitag_search(
            q="",
            prompt="",
            page=1,
            page_size=60,
            sort="recent",
            time_range="month",
            nai_only=True,
            safe_only=False,
            creator="alice",
            tags="cat,night",
            model="v4.5",
            min_images=2,
            max_images=3,
        )

    assert [item["id"] for item in result["items"]] == ["match-1"]
    assert result["filters"] == {
        "creator": "alice",
        "tags": ["cat", "night"],
        "model": "v4.5",
        "min_images": 2,
        "max_images": 3,
        "time_range": "month",
    }


def test_online_favorite_has_its_own_gallery_identity_and_snapshot(tmp_path: Path) -> None:
    favorite_path = tmp_path / "favorites.json"
    with patch.object(favorites, "FAV_PATH", favorite_path):
        result = favorites.toggle(
            "148292785",
            "aitag-online",
            title="Online title",
            creator="Alice",
            cover_url="/api/nai/aitag/cover/148292785",
        )
        refs = favorites.list_refs()

    assert result["favorited"] is True
    assert refs == [
        {
            "gallery_id": "aitag-online",
            "work_id": "148292785",
            "key": "aitag-online:148292785",
            "added_at": refs[0]["added_at"],
            "title": "Online title",
            "creator": "Alice",
            "cover_url": "/api/nai/aitag/cover/148292785",
        }
    ]


def test_home_gallery_exposes_online_filters_favorites_and_character_slots() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    # 线上换角面板已从 app.js 拆到 app-online-remix.js（index.html 按序加载两者）
    app = (root / "web" / "app.js").read_text(encoding="utf-8") + (
        root / "web" / "app-online-remix.js"
    ).read_text(encoding="utf-8")
    core = (root / "web" / "app-core.js").read_text(encoding="utf-8")

    for element_id in (
        "aitagCreator",
        "aitagTags",
        "aitagMinImages",
        "aitagMaxImages",
    ):
        assert f'id="{element_id}"' in html
    assert "/api/nai/aitag/favorites" in core
    assert "renderOnlineCharacterCandidates" in app
    assert "/api/plugin/char-swap/presets?gender=female" in app
    assert "/api/plugin/char-swap/ark-library?gender=female" in app
    assert "openAitagAssetWorkbench" not in app
    assert 'href="/aitag-library"' not in html
    assert "角色与画风草稿" in app
    # Online remix must share the local char-swap shell + usable badges + generate path.
    assert 'class="char-swap-panel online-remix-panel is-compact"' in app
    assert "onlineTargetUsable" in app
    assert "onlineUsableBadge" in app
    assert "generateOnlineCurrentDraft" in app
    assert "generateOnlineAllDrafts" in app
    assert "单张试生成" in app
    assert "换男角·全部" in app
    assert "换女角·全部" in app
    assert "画风·全部图片" in app
    assert "gender_scope" in app
    assert "all_pages" in app
    assert "base_comment" in app
    assert "base_comments" in app
    assert "onlineWired" in app
    assert "resetOriginal" in app
    assert "onlineWorkIdForGenerate" in app
    assert "work_id_str" in app
    assert "source_gallery_id" in app
    assert "is-partial" in app or "partial" in app
    assert "localStorage" in app and "online draft localStorage save failed" in app
    assert "source_title" in app
    assert "我的 OC" in app
    assert "applyOnlineSelectedTargetToSlot" in app
    assert "applyOnlineTargetItem" in app
    assert "先在下方点一个角色" in app
    assert "点角色卡即换到当前槽" in app
    assert "onlineImageArrayIndexes" in app
    assert "character_caption" in app
    assert "生成已换页" in app
    assert "aria-disabled" in app
    assert "换角面板初始化失败" in (root / "web" / "app-detail.js").read_text(encoding="utf-8")
    studio = (root / "web" / "studio.js").read_text(encoding="utf-8")
    assert "pickAitagDraftFromServerResult" in studio
    assert "switchAitagPage" in studio
    assert "studioAitagPages" in studio or "studio-aitag-pages" in studio
    assert "if (!isAitagGallery())" not in app[app.index("const topRight"):app.index("card.appendChild(topRight)")]


def test_builtin_swap_target_uses_the_same_seed_as_local_gallery() -> None:
    preset = {
        "id": "skadi_f",
        "label": "斯卡蒂",
        "gender": "female",
        "identity": ["skadi_(arknights)", "1girl", "female_focus"],
        "body": ["tall"],
        "appearance": ["white_hair", "red_eyes"],
        "source": "builtin",
    }
    with patch.object(aitag_routes, "list_char_presets", return_value=[preset]):
        record = aitag_routes._builtin_target_record("preset:female:skadi_f")

    assert record is not None
    assert record["reference_id"] == "preset:female:skadi_f"
    assert record["trigger"] == "skadi_(arknights)"
    assert record["identity"] == preset["identity"]
    assert record["appearance"] == ["tall", "white_hair", "red_eyes"]


def test_builtin_oc_preset_keeps_whole_caption_for_online_replace() -> None:
    preset = {
        "id": "feijibei",
        "label": "费济北",
        "gender": "male",
        "kind": "oc",
        "char_caption": "1boy, 18 years old, slim, youthful, black hair",
        "identity": ["1boy", "male_focus"],
        "source": "custom",
        "is_custom": True,
    }
    with patch.object(aitag_routes, "list_char_presets", return_value=[preset]):
        record = aitag_routes._builtin_target_record("preset:male:feijibei")

    assert record["kind"] == "oc"
    assert record["char_caption"] == preset["char_caption"]
    assert "18 years old" not in record["appearance"]
    assert "youthful" not in record["appearance"]


def test_catalog_custom_oc_keeps_whole_caption_when_raw_omits_it() -> None:
    item = {
        "reference_id": "ref_feijibei",
        "source": "custom",
        "label": "费济北",
        "gender": "male",
        "character_caption": "1boy, 18 years old, slim, youthful, black hair",
        "raw": {
            "name": "费济北",
            "gender": "male",
            "core_tags": ["1boy", "18 years old", "slim"],
            "source": "custom",
        },
    }
    record = aitag_routes._merge_catalog_target_record(item, "ref_feijibei")
    assert record["kind"] == "oc"
    assert record["char_caption"] == item["character_caption"]
    assert record["is_custom"] is True


def test_online_detail_page_index_matches_image_array() -> None:
    from aitag_core.external import normalize_aitag_detail

    detail = normalize_aitag_detail(
        {
            "id": "148389562",
            "title": "multi page",
            "images": [
                {"id": "p0", "aiJson": {"Software": "NovelAI"}},
                {"id": "p1", "aiJson": {"Software": "NovelAI"}},
            ],
        }
    )
    payload = aitag_routes._detail_payload(detail)
    assert [image["page_index"] for image in payload["images"]] == [0, 1]


def test_named_catalog_record_does_not_become_oc() -> None:
    item = {
        "reference_id": "ref_skadi",
        "source": "animadex",
        "label": "Skadi",
        "gender": "female",
        "character_caption": "girl, skadi (arknights), white hair",
        "trigger": "skadi_(arknights)",
        "raw": {
            "name": "Skadi",
            "trigger": "skadi_(arknights)",
            "gender": "female",
        },
    }
    record = aitag_routes._merge_catalog_target_record(item, "ref_skadi")
    assert record.get("kind") != "oc"
    assert "char_caption" not in record or record.get("kind") != "oc"
    assert record["trigger"] == "skadi_(arknights)"

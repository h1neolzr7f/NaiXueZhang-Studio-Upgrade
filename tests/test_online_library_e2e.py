from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from db import Database
from library_lifecycle import RemoteCache
from online_library import (
    add_to_my_library,
    derive_local_transform,
    favorite_remote,
    list_favorites,
    reset_online_state_for_tests,
    search_online,
    set_provider_fail_mode,
    unload_online_favorites_for_tests,
)


class OnlineLibraryE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        reset_online_state_for_tests()

    def test_search_favorite_materialize_lineage_and_local_survives_outage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "gallery.db")
            spec = SimpleNamespace(images_dir=root / "images")
            spec.images_dir.mkdir()
            cache = RemoteCache(root / "cache", max_items=2)
            try:
                with patch("online_library.data_dir", return_value=root):
                    found = search_online("角色")
                    self.assertTrue(found["ok"])
                    self.assertGreaterEqual(len(found["items"]), 1)
                    fav = favorite_remote("syn-1")
                    self.assertTrue(fav["favorite"])
                    self.assertEqual(fav["item"]["lifecycle"], "remote")
                    with patch("online_library._cache", return_value=cache), patch(
                        "gallery_catalog.get_spec", return_value=spec
                    ), patch("gallery_catalog.ensure_gallery_dirs"), patch(
                        "library_writer.get_db", return_value=db
                    ), patch("library_writer.ensure_gallery_dirs"), patch(
                        "online_library.stable_work_id", return_value=501
                    ), patch("online_library._is_materialized", return_value=False):
                        added = add_to_my_library("syn-1", gallery_id="codex")
                    self.assertTrue(added["ok"])
                    self.assertEqual(added["lifecycle"], "materialized")
                    work = db.conn.execute("SELECT list_json FROM works WHERE id = 501").fetchone()
                    self.assertIn("synthetic", work["list_json"])
                    image = db.conn.execute(
                        "SELECT source_sha256 FROM work_images WHERE work_id = 501"
                    ).fetchone()
                    self.assertTrue(image["source_sha256"])
                    cache.evict_all()
                    still = db.conn.execute("SELECT id FROM works WHERE id = 501").fetchone()
                    self.assertIsNotNone(still)
                    with patch("online_library._cache", return_value=cache), patch(
                        "gallery_catalog.get_spec", return_value=spec
                    ), patch("gallery_catalog.ensure_gallery_dirs"), patch(
                        "library_writer.get_db", return_value=db
                    ), patch("library_writer.ensure_gallery_dirs"), patch(
                        "online_library.stable_work_id",
                        side_effect=lambda *parts: 601 if "derive" in str(parts[0]) else 501,
                    ):
                        derived = derive_local_transform("syn-1", gallery_id="codex")
                    self.assertTrue(derived["ok"])
                    self.assertEqual(derived["parent_work_id"], 501)
                    self.assertFalse(derived["paid"])
                    self.assertIn("local derive", derived["lineage"]["transform_summary"])
                    child = db.conn.execute("SELECT list_json FROM works WHERE id = 601").fetchone()
                    self.assertIn("synthetic-derive", child["list_json"])
                    self.assertIn("501", child["list_json"])
                    unload_online_favorites_for_tests()
                    restarted = list_favorites()
                    self.assertEqual(len(restarted), 1)
                    self.assertTrue(restarted[0].get("title") or restarted[0].get("favorite"))
                    db.close()
                    reopened = Database(root / "gallery.db")
                    try:
                        again = reopened.conn.execute("SELECT list_json FROM works WHERE id = 501").fetchone()
                        self.assertIn("syn-1", again["list_json"])
                    finally:
                        reopened.close()
                    set_provider_fail_mode("unavailable")
                    offline = search_online("角色")
                    self.assertFalse(offline["ok"])
                    self.assertTrue(offline["local_library_available"])
                    favorites = list_favorites()
                    self.assertEqual(favorites[0]["available"], False)
            finally:
                try:
                    db.close()
                except Exception:
                    pass
                reset_online_state_for_tests()


class ClassicGalleryOnlineUiTests(unittest.TestCase):
    def test_classic_gallery_exposes_online_discover_without_ninth_nav(self) -> None:
        html = Path("web/index.html").read_text(encoding="utf-8")
        script = Path("web/online-discover.js").read_text(encoding="utf-8")
        nav = Path("web/shared/site-nav.js").read_text(encoding="utf-8")
        self.assertIn("onlineDiscoverBtn", html)
        self.assertIn("online-discover.js", html)
        self.assertIn("/api/online/search", script)
        self.assertIn("加入我的图库", script)
        self.assertIn("收藏（不下载）", script)
        self.assertNotIn('label: "在线发现"', nav)

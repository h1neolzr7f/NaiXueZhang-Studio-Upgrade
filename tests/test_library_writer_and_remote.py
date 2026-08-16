from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from library_writer import MaterializePage, materialize_asset
from remote_asset import RemoteAssetRef
from scripts.gallery_import_common import upsert_local_work


class RemoteIdentityTests(unittest.TestCase):
    def test_rejects_opaque_id_without_provider(self) -> None:
        with self.assertRaises(ValueError):
            RemoteAssetRef(provider_id="", remote_id="123")
        ref = RemoteAssetRef.for_pixiv("99", source_url="https://www.pixiv.net/artworks/99")
        self.assertEqual(ref.qualified_id, "pixiv:99:v1")
        self.assertEqual(ref.identity_version, 1)


class LibraryWriterTests(unittest.TestCase):
    def test_materialize_writes_sha_and_remote_ref(self) -> None:
        from unittest.mock import patch

        from db import Database

        with tempfile.TemporaryDirectory() as raw:
            db = Database(Path(raw) / "gallery.db")
            try:
                with patch("library_writer.get_db", return_value=db), patch(
                    "library_writer.ensure_gallery_dirs"
                ):
                    result = materialize_asset(
                        "codex",
                        work_id=4242,
                        title="dropped",
                        remote_ref=RemoteAssetRef.for_drop("abc123", folder="拖入", filename="a.png"),
                        pages=[
                            MaterializePage(
                                relative_path="拖入/a.png",
                                source_sha256="abc123",
                                prompt_text="1girl",
                            )
                        ],
                        source="local-drop:拖入",
                    )
                self.assertTrue(result.ok)
                image = db.conn.execute(
                    "SELECT source_sha256, local_path FROM work_images WHERE work_id = 4242"
                ).fetchone()
                self.assertEqual(image["source_sha256"], "abc123")
                work = db.conn.execute("SELECT list_json FROM works WHERE id = 4242").fetchone()
                self.assertIn("local-drop", work["list_json"])
                self.assertIn("abc123", work["list_json"])
            finally:
                db.close()

    def test_upsert_local_work_delegates_and_import_module_has_no_direct_sql(self) -> None:
        source = Path("scripts/gallery_import_common.py").read_text(encoding="utf-8")
        self.assertNotIn("INSERT INTO works", source)
        self.assertNotIn("INSERT INTO work_images", source)
        self.assertIn("materialize_asset", source)


class NoDirectLibraryWriteGuardTests(unittest.TestCase):
    ALLOWED = {
        "library_writer.py",
        "db.py",
        "db_crawler_writes.py",
        "pixiv_nai_intake.py",
        "gallery_maintenance.py",
    }

    def test_provider_modules_do_not_insert_library_rows(self) -> None:
        forbidden = []
        for path in (
            Path("qq_gallery_ingest.py"),
            Path("crawler_qq.py"),
            Path("scripts/gallery_import_common.py"),
            Path("scripts/import_codex_gallery.py"),
            Path("routes/gallery.py"),
            Path("acquire/synthetic_provider.py"),
            Path("online_library.py"),
        ):
            text = path.read_text(encoding="utf-8")
            if "INSERT INTO works" in text or "INSERT INTO work_images" in text:
                forbidden.append(str(path))
        self.assertEqual(forbidden, [])

    def test_allowed_writers_are_explicit(self) -> None:
        for name in self.ALLOWED:
            self.assertTrue(Path(name).is_file(), name)


if __name__ == "__main__":
    unittest.main()

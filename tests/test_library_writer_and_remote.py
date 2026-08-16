from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from library_writer import MaterializePage, materialize_asset
from remote_asset import RemoteAssetRef


class RemoteIdentityTests(unittest.TestCase):
    def test_rejects_opaque_id_without_provider_or_source(self) -> None:
        with self.assertRaises(ValueError):
            RemoteAssetRef(provider_id="", remote_id="123")
        with self.assertRaises(ValueError):
            RemoteAssetRef(provider_id="provider-x", remote_id="42")
        ref = RemoteAssetRef.for_pixiv("99")
        self.assertTrue(ref.qualified_id.startswith("pixiv:99:"))
        self.assertTrue(ref.qualified_id.endswith(":v1"))
        self.assertEqual(ref.source_url, "https://www.pixiv.net/artworks/99")
        self.assertEqual(ref.identity_version, 1)
        left = RemoteAssetRef(provider_id="provider-x", remote_id="42", source_url="https://a.example/1")
        right = RemoteAssetRef(provider_id="provider-x", remote_id="42", source_url="https://b.example/2")
        self.assertNotEqual(left.qualified_id, right.qualified_id)


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
        "routes/gallery.py",
        "routes/compliance.py",
        "qq_gallery_ingest.py",
    }
    WRITE_RE = re.compile(
        r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(works|work_images)\b",
        re.IGNORECASE,
    )
    SKIP_PARTS = {
        ".git",
        "node_modules",
        "__pycache__",
        "tests",
        "frontend",
        "runtime",
        ".venv",
        ".tmp",
        "site-packages",
        "dist",
        "build",
    }

    def test_provider_modules_do_not_insert_library_rows(self) -> None:
        forbidden = []
        for path in Path(".").rglob("*.py"):
            if any(part in self.SKIP_PARTS for part in path.parts):
                continue
            rel = path.as_posix().lstrip("./")
            if path.name in self.ALLOWED or rel in self.ALLOWED:
                continue
            text = path.read_text(encoding="utf-8")
            if self.WRITE_RE.search(text):
                forbidden.append(rel)
        self.assertEqual(forbidden, [])

    def test_write_guard_skips_windows_portable_runtime_tree(self) -> None:
        self.assertTrue({"runtime", ".venv", ".tmp", "site-packages"} <= self.SKIP_PARTS)
        planted = Path("runtime/Lib/site-packages/torch/_functorch/config.py")
        self.assertTrue(any(part in self.SKIP_PARTS for part in planted.parts))

    def test_allowed_writers_are_explicit(self) -> None:
        for name in self.ALLOWED:
            self.assertTrue(Path(name).is_file(), name)

    def test_db_failure_after_file_write_does_not_leave_orphan(self) -> None:
        from online_library import add_to_my_library, reset_online_state_for_tests

        reset_online_state_for_tests()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dest = root / "online" / "synthetic" / "syn-1.png"
            dest.parent.mkdir(parents=True)
            spec = type("Spec", (), {"images_dir": root})()
            with patch("gallery_catalog.get_spec", return_value=spec), patch(
                "gallery_catalog.ensure_gallery_dirs"
            ), patch("online_library._cache") as cache, patch(
                "online_library.materialize_asset", side_effect=RuntimeError("db down")
            ), patch("online_library.stable_work_id", return_value=501):
                cache.return_value.put.return_value = root / "cache.bin"
                with self.assertRaises(RuntimeError):
                    add_to_my_library("syn-1", gallery_id="codex")
            self.assertFalse(dest.exists())
        reset_online_state_for_tests()


if __name__ == "__main__":
    unittest.main()

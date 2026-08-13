from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.verify_release_stage import (
    CORE_SEED_FILES,
    FULL_REQUIRED_AITAG_FILES,
    FULL_REQUIRED_ROUTE_PATHS,
    FULL_SEED_FILES,
    FULL_REQUIRED_WEB_FILES,
    verify,
)


class ReleaseStageVerifierTests(unittest.TestCase):
    def _write_seed_manifest(self, stage: Path, profile: str) -> None:
        required = CORE_SEED_FILES if profile == "core" else FULL_SEED_FILES
        entries = []
        for relative in sorted(required):
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"seed:{relative}\n", encoding="utf-8")
            entries.append({
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        (stage / "data" / "seed_manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "release_profile": profile,
                "generation_calls": 0,
                "files": entries,
            }),
            encoding="utf-8",
        )

    def _write_release_manifest(self, stage: Path, profile: str) -> None:
        inventory = []
        for path in sorted(stage.rglob("*")):
            if not path.is_file() or path.name == "release_manifest.json":
                continue
            inventory.append({
                "path": path.relative_to(stage).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        (stage / "release_manifest.json").write_text(
            json.dumps({
                "schema_version": 2,
                "release_profile": profile,
                "inventory_algorithm": "sha256",
                "file_count": len(inventory),
                "bytes": sum(entry["bytes"] for entry in inventory),
                "inventory": inventory,
            }),
            encoding="utf-8",
        )

    def test_full_gate_covers_each_preserved_product_surface(self) -> None:
        for path in (
            "/",
            "/favorites",
            "/queue",
            "/studio",
            "/app",
            "/remix",
            "/generated",
            "/settings",
            "/progress",
            "/butler",
            "/director",
            "/pixiv",
            "/ops",
            "/tag-assets",
            "/aitag-library",
            "/pipeline",
            "/references",
            "/nai-tags",
            "/maintenance",
            "/api/ai_works_search",
            "/api/nai/generate",
            "/api/studio/optimize",
            "/api/butler/status",
            "/api/director/catalog",
            "/api/pixiv/accounts",
            "/api/nai/references",
            "/api/nai/aitag/status",
            "/api/nai/aitag/search",
            "/api/nai/aitag/work/{work_id}/characters",
            "/api/nai/aitag/favorites",
            "/api/nai/aitag/favorites/works",
            "/api/nai/aitag/favorites/{work_id}/toggle",
            "/api/nai/aitag/work/{work_id}/draft",
            "/api/nai/aitag/drafts/latest/restore",
            "/api/nai/aitag/drafts/{draft_id}",
            "/api/nai/aitag/cache/clear",
            "/api/settings/status",
            "/api/pipeline/status",
            "/api/crawler/pixiv/task",
            "/api/maintenance/storage",
        ):
            self.assertIn(path, FULL_REQUIRED_ROUTE_PATHS)
        for page in (
            "web/index.html",
            "web/studio.html",
            "web/workspace.html",
            "web/remix.html",
            "web/generated.html",
            "web/settings.html",
            "web/progress.html",
            "web/butler.html",
            "web/director.html",
            "web/pixiv.html",
            "web/ops.html",
            "web/tag-assets.html",
            "web/tag-assets.js",
            "web/tag-assets.css",
            "web/pipeline.html",
            "web/references.html",
            "web/nai-tags.html",
            "web/maintenance.html",
        ):
            self.assertIn(page, FULL_REQUIRED_WEB_FILES)
    def _mark_core(self, stage: Path) -> None:
        # ``_stage`` models the complete bundle.  Converting that fixture to the
        # core profile must mirror make_release.ps1 and remove full-only AITag
        # federation modules before exercising an unrelated core guard.
        for relative_path in FULL_REQUIRED_AITAG_FILES:
            path = stage / relative_path
            if path.is_file():
                path.unlink()
        for relative_path in FULL_REQUIRED_WEB_FILES:
            path = stage / relative_path
            if path.is_file():
                path.unlink()
        # core 档只带 CORE_SEED_FILES；full-only 种子（含 butler/director 目录数据）必须移除
        for relative_path in FULL_SEED_FILES - CORE_SEED_FILES:
            path = stage / relative_path
            if path.is_file():
                path.unlink()
        plugin_root = stage / "web" / "plugins" / "char-swap"
        if plugin_root.is_dir():
            __import__("shutil").rmtree(plugin_root)
        (stage / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (stage / "BUNDLE_NOTICE.txt").write_text(
            "No downloaded images are included.\n", encoding="utf-8"
        )
        (stage / "THIRD_PARTY_NOTICES.md").write_text(
            "# Third-party notices\n", encoding="utf-8"
        )
        requirements = (
            "fastapi==0.136.3\nhttpx==0.28.1\npillow==12.2.0\n"
            "psutil==7.2.2\nuvicorn==0.49.0\n"
        )
        (stage / "requirements.txt").write_text(requirements, encoding="utf-8")
        (stage / "requirements.lock.txt").write_text(requirements, encoding="utf-8")
        for launcher_name in ("ONE_CLICK_START.bat", "一键启动.bat"):
            (stage / launcher_name).write_text(
                '@echo off\ncall "%~dp0START_GALLERY.bat" %*\n',
                encoding="utf-8",
            )
        for relative_path in (
            "data/char_tag_groups.json",
            "data/char_tag_index.json",
            "data/danbooru_creature.json",
            "gallery_maintenance.py",
            "gallery_snapshot.py",
            "nai_tag_index.py",
            "routes/gallery.py",
            "routes/maintenance.py",
            "routes/nai_tags.py",
            "web/core-gallery.js",
            "web/core-intake.js",
            "web/gallery-maintenance.js",
            "web/index.html",
            "web/maintenance.html",
            "web/nai-tags.html",
            "web/nai-tags.js",
            "web/progress.html",
        ):
            path = stage / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n" if path.suffix == ".json" else "# fixture\n", encoding="utf-8")
        self._write_seed_manifest(stage, "core")
        self._write_release_manifest(stage, "core")

    def _stage(self, root: Path) -> Path:
        stage = root / "stage"
        (stage / "data" / "images").mkdir(parents=True)
        (stage / "config.json").write_text(
            '{"base_url":"","cdn_url":"","legacy_aitag_crawler_enabled":false,'
            '"aitag_online_enabled":true,"aitag_online_cache_ttl_sec":600,'
            '"aitag_online_cache_max_bytes":67108864,"aitag_online_timeout_sec":30,'
            '"aitag_draft_ttl_sec":2592000}',
            encoding="utf-8",
        )
        for module_name in (
            "nai_prompt_tags.py",
            "pixiv_nai_source.py",
            "pixiv_nai_intake.py",
            "pixiv_nai_crawler.py",
        ):
            (stage / module_name).write_text("# fixture\n", encoding="utf-8")
        for relative_path in FULL_REQUIRED_AITAG_FILES:
            path = stage / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        for relative_path in FULL_REQUIRED_WEB_FILES:
            path = stage / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        plugin_root = stage / "web" / "plugins" / "char-swap"
        plugin_root.mkdir(parents=True, exist_ok=True)
        (plugin_root / "plugin.js").write_text(
            'import "./state.js?v=58";\n', encoding="utf-8"
        )
        (plugin_root / "state.js").write_text("export const state = {};\n", encoding="utf-8")
        db_path = stage / "data" / "aitag.db"
        connection = sqlite3.connect(db_path)
        connection.executescript(
            "CREATE TABLE works(id INTEGER PRIMARY KEY);"
            "CREATE TABLE work_images(work_id INTEGER, page_index INTEGER, "
            "downloaded INTEGER, local_path TEXT);"
            "INSERT INTO works(id) VALUES (1);"
        )
        connection.commit()
        connection.close()
        digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
        (stage / "data" / "sample_manifest.json").write_text(
            json.dumps({"database_sha256": digest}), encoding="utf-8"
        )
        self._write_seed_manifest(stage, "full")
        self._write_release_manifest(stage, "full")
        return stage

    def test_final_manifest_hash_is_enforced_without_importing_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            result = verify(stage, require_sample=False, import_server=False)
            self.assertTrue(result["ok"])
            with (stage / "data" / "aitag.db").open("ab") as handle:
                handle.write(b"changed")
            with self.assertRaisesRegex(RuntimeError, "hash does not match"):
                verify(stage, require_sample=False, import_server=False)

    def test_runtime_sqlite_sidecars_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            (stage / "data" / "aitag.db-wal").write_bytes(b"")
            with self.assertRaisesRegex(RuntimeError, "runtime cache files"):
                verify(stage, require_sample=False, import_server=False)

    def test_release_manifest_is_required_and_hashes_every_final_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            (stage / "release_manifest.json").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "release_manifest"):
                verify(stage, require_sample=False, import_server=False)

        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            with (stage / "nai_prompt_tags.py").open("a", encoding="utf-8") as handle:
                handle.write("# changed after assembly\n")
            with self.assertRaisesRegex(RuntimeError, "manifest hash/size"):
                verify(stage, require_sample=False, import_server=False)

    def test_full_web_dependency_closure_rejects_missing_char_swap_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            (stage / "web" / "plugins" / "char-swap" / "state.js").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "web dependency"):
                verify(stage, require_sample=False, import_server=False)

    def test_starter_library_hash_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            with (stage / "data" / "char_tag_index.json").open("a", encoding="utf-8") as handle:
                handle.write("changed\n")
            with self.assertRaisesRegex(RuntimeError, "starter-library (size|hash)"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_rejects_heavy_feature_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            (stage / "butler_service.py").write_text("# must not ship\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "Core-forbidden"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_requires_license_notices_and_locked_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            (stage / "LICENSE").unlink()
            with self.assertRaisesRegex(FileNotFoundError, "Core release file"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_rejects_downloaded_gallery_images(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            (stage / "data" / "images" / "pixiv-downloaded.png").write_bytes(
                b"not public source code"
            )

            with self.assertRaisesRegex(RuntimeError, "downloaded image"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_rejects_restricted_live2d_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            model = stage / "web" / "vendor" / "live2d-models" / "hiyori"
            model.mkdir(parents=True)
            (model / "Hiyori.moc3").write_bytes(b"restricted model")

            with self.assertRaisesRegex(RuntimeError, "restricted asset"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_rejects_heavy_or_unpinned_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            with (stage / "requirements.lock.txt").open("a", encoding="utf-8") as handle:
                handle.write("playwright>=1.49.0\n")

            with self.assertRaisesRegex(RuntimeError, "Core dependency boundary"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_rejects_excluded_feature_references_in_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            (stage / "web" / "core-gallery.js").write_text(
                "fetch('/studio');\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(RuntimeError, "excluded feature reference"):
                verify(stage, require_sample=False, import_server=False)

    def test_core_profile_rejects_full_suite_runtime_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage = self._stage(Path(temp))
            self._mark_core(stage)
            (stage / "data" / "post_pipeline.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "full-suite configuration"):
                verify(stage, require_sample=False, import_server=False)


if __name__ == "__main__":
    unittest.main()

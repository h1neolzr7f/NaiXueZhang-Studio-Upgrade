import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.verify_release_stage import (
    FULL_REQUIRED_AITAG_FILES,
    FULL_REQUIRED_ROUTE_PATHS,
    FULL_SEED_FILES,
    FULL_REQUIRED_WEB_FILES,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCRIPT = PROJECT_ROOT / "scripts" / "make_release.ps1"
ZIP_SCRIPT = PROJECT_ROOT / "scripts" / "zip_release.py"
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_release_stage.py"


@unittest.skipUnless(os.name == "nt", "make_release.ps1 packaging contract is Windows-only")
class ReleaseScriptSafetyTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp_root = Path(self._temp_dir.name)
        self.fixture_project = self.temp_root / "fixture project"
        fixture_scripts = self.fixture_project / "scripts"
        fixture_scripts.mkdir(parents=True)
        shutil.copy2(SOURCE_SCRIPT, fixture_scripts / SOURCE_SCRIPT.name)
        shutil.copy2(ZIP_SCRIPT, fixture_scripts / ZIP_SCRIPT.name)
        shutil.copy2(VERIFY_SCRIPT, fixture_scripts / VERIFY_SCRIPT.name)
        for template_name in (
            "core_web_app.js",
            "core_web_index.html",
            "core_web_intake.js",
            "core_web_progress.html",
            "crawler_control_core.py",
            "pixiv_accounts_core.py",
            "routes_gallery_core.py",
            "routes_nai_tags_core.py",
            "server_shared_core.py",
        ):
            shutil.copy2(PROJECT_ROOT / "scripts" / template_name, fixture_scripts / template_name)
        (fixture_scripts / "server_core.py").write_text(
            "class Route:\n"
            "    def __init__(self, path): self.path = path\n"
            "class App:\n"
            "    routes = [Route('/'), Route('/api/config'), "
            "Route('/api/crawler/pixiv/task'), Route('/api/crawler/pixiv/report'), "
            "Route('/api/nai-tags'), Route('/nai-tags')]\n"
            "app = App()\n",
            encoding="utf-8",
        )
        fixture_data = self.fixture_project / "data"
        fixture_data.mkdir()
        for relative_path in sorted(FULL_SEED_FILES | {
            "data/seed_manifest.json",
            "data/char_tag_groups.json",
            "data/sanitize_blocklist.json",
            "data/tag_dict.json",
            "data/nai_token.local.example.json",
            "data/pixiv_accounts.local.example.json",
            "data/ai.local.example.json",
        }):
            source = PROJECT_ROOT / relative_path
            destination = self.fixture_project / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        (self.fixture_project / "INSTALL.bat").write_text("@echo off\n", encoding="utf-8")
        for launcher_name in ("ONE_CLICK_START.bat", "一键启动.bat"):
            (self.fixture_project / launcher_name).write_text(
                '@echo off\ncall "%~dp0START_GALLERY.bat" %*\nexit /b %errorlevel%\n',
                encoding="utf-8",
            )
        (self.fixture_project / "requirements.lock.txt").write_text(
            "example==1.0\n",
            encoding="utf-8",
        )
        (self.fixture_project / "requirements.txt").write_text(
            "example>=1.0\n",
            encoding="utf-8",
        )
        (self.fixture_project / "requirements.core.txt").write_text(
            "fastapi>=0.115.0\nhttpx>=0.27.0\n",
            encoding="utf-8",
        )
        (self.fixture_project / "requirements.core.lock.txt").write_text(
            "fastapi==0.136.3\nhttpx==0.28.1\n",
            encoding="utf-8",
        )
        (self.fixture_project / "LICENSE").write_text("MIT License\n", encoding="utf-8")
        (self.fixture_project / "BUNDLE_NOTICE.txt").write_text(
            "No downloaded images are included.\n", encoding="utf-8"
        )
        (self.fixture_project / "THIRD_PARTY_NOTICES.md").write_text(
            "# Third-party notices\n", encoding="utf-8"
        )
        (self.fixture_project / "setup_web.ps1").write_text(
            "$ErrorActionPreference = 'Stop'\n",
            encoding="utf-8",
        )
        (self.fixture_project / "config.release.json").write_text(
            '{"base_url":"","cdn_url":"","legacy_aitag_crawler_enabled":false,'
            '"aitag_online_enabled":true,"aitag_online_cache_ttl_sec":600,'
            '"aitag_online_cache_max_bytes":67108864,"aitag_online_timeout_sec":30,'
            '"aitag_draft_ttl_sec":2592000,'
            '"search_query":"NAI"}',
            encoding="utf-8",
        )
        for module_name in (
            "gallery_maintenance.py",
            "gallery_snapshot.py",
            "nai_prompt_tags.py",
            "nai_tag_index.py",
            "pixiv_nai_source.py",
            "pixiv_nai_intake.py",
            "pixiv_nai_crawler.py",
            "pixiv_nai_preflight.py",
            "pixiv_browser_source.py",
            "pixiv_public_source.py",
        ):
            (self.fixture_project / module_name).write_text("# fixture\n", encoding="utf-8")
        for relative_path in (
            "routes/maintenance.py",
            "routes/nai_tags.py",
            "web/gallery-maintenance.js",
            "web/maintenance.html",
            "web/nai-tags.html",
            "web/nai-tags.js",
            *sorted(FULL_REQUIRED_AITAG_FILES),
            *sorted(FULL_REQUIRED_WEB_FILES),
        ):
            path = self.fixture_project / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n" if path.suffix == ".json" else "# fixture\n", encoding="utf-8")
        char_swap = self.fixture_project / "web" / "plugins" / "char-swap"
        char_swap.mkdir(parents=True, exist_ok=True)
        (char_swap / "plugin.js").write_text(
            'import "./state.js?v=58";\n', encoding="utf-8"
        )
        (char_swap / "state.js").write_text("export const state = {};\n", encoding="utf-8")
        full_routes = sorted(FULL_REQUIRED_ROUTE_PATHS | {"/api/config"})
        route_items = ", ".join(f"Route({path!r})" for path in full_routes)
        (self.fixture_project / "server.py").write_text(
            "class Route:\n"
            "    def __init__(self, path): self.path = path\n"
            "class App:\n"
            f"    routes = [{route_items}]\n"
            "app = App()\n",
            encoding="utf-8",
        )
        nai_char_modules = self.fixture_project / "nai_char_modules"
        nai_char_modules.mkdir()
        (nai_char_modules / "__init__.py").write_text(
            "from .generation import BUILD_MARKER\n",
            encoding="utf-8",
        )
        (nai_char_modules / "generation.py").write_text(
            "BUILD_MARKER = 'refactored-nai-char'\n",
            encoding="utf-8",
        )
        (self.fixture_project / "nai_char.py").write_text(
            "from nai_char_modules import BUILD_MARKER\n",
            encoding="utf-8",
        )
        (fixture_data / "pixiv_launch.sample.json").write_text(
            '{"ai":{"provider":"","api_base":"","model":""}}',
            encoding="utf-8",
        )
        (fixture_data / "post_pipeline.sample.json").write_text("{}", encoding="utf-8")
        self.sentinel = self.fixture_project / "source-must-survive.txt"
        self.sentinel.write_text("source tree is intact", encoding="utf-8")

    def tearDown(self):
        self._temp_dir.cleanup()

    def run_release(self, release_root: Path, package_name: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.fixture_project / "scripts" / SOURCE_SCRIPT.name),
                "-ReleaseRoot",
                str(release_root),
                "-PackageName",
                package_name,
                "-SkipZip",
                "-SkipShortcut",
                "-SkipSampleData",
                "-AllowDirtySource",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def run_default_release(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.fixture_project / "scripts" / SOURCE_SCRIPT.name),
                "-SkipZip",
                "-SkipShortcut",
                "-SkipSampleData",
                "-AllowDirtySource",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def run_release_with_zip(
        self,
        release_root: Path,
        package_name: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.fixture_project / "scripts" / SOURCE_SCRIPT.name),
                "-ReleaseRoot",
                str(release_root),
                "-PackageName",
                package_name,
                "-SkipShortcut",
                "-SkipSampleData",
                "-AllowDirtySource",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def run_core_release(
        self,
        release_root: Path,
        package_name: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.fixture_project / "scripts" / SOURCE_SCRIPT.name),
                "-ReleaseRoot",
                str(release_root),
                "-PackageName",
                package_name,
                "-Profile",
                "core",
                "-SkipZip",
                "-SkipShortcut",
                "-SkipSampleData",
                "-AllowDirtySource",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def test_rejects_stage_equal_to_source_without_deleting_source(self):
        result = self.run_release(self.temp_root, self.fixture_project.name)
        output = result.stdout + result.stderr

        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("Release stage must be separate from the project source", output)
        self.assertTrue(self.sentinel.exists(), output)

    def test_rejects_stage_inside_source_before_creating_it(self):
        stage = self.fixture_project / "release-child"

        result = self.run_release(self.fixture_project, stage.name)
        output = result.stdout + result.stderr

        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("Release stage must be separate from the project source", output)
        self.assertFalse(stage.exists(), output)
        self.assertTrue(self.sentinel.exists(), output)

    def test_rejects_stage_that_contains_source_without_deleting_source(self):
        result = self.run_release(self.temp_root.parent, self.temp_root.name)
        output = result.stdout + result.stderr

        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("Release stage must be separate from the project source", output)
        self.assertTrue(self.sentinel.exists(), output)

    def test_default_stage_is_in_external_releases_directory(self):
        expected_stage = self.temp_root / "releases" / "pixiv-nai-gallery"

        result = self.run_default_release()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(expected_stage.is_dir(), result.stdout + result.stderr)
        self.assertTrue(self.sentinel.exists(), result.stdout + result.stderr)

    def test_default_build_rejects_non_git_or_uncontrolled_source(self):
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.fixture_project / "scripts" / SOURCE_SCRIPT.name),
                "-SkipZip",
                "-SkipShortcut",
                "-SkipSampleData",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not a Git checkout", result.stdout + result.stderr)

    def test_smoke_import_does_not_leave_python_cache_in_release(self):
        release_root = self.temp_root / "release-root"
        result = self.run_release(release_root, "clean-package")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        stage = release_root / "clean-package"
        self.assertEqual(list(stage.rglob("__pycache__")), [])
        self.assertEqual(list(stage.rglob("*.pyc")), [])

    def test_rejects_package_name_path_traversal_without_deleting_outside_directory(self):
        release_root = self.temp_root / "release-root"
        victim = self.temp_root / "victim"
        victim.mkdir()
        victim_sentinel = victim / "must-survive.txt"
        victim_sentinel.write_text("do not delete", encoding="utf-8")

        result = self.run_release(release_root, r"..\victim")
        output = result.stdout + result.stderr

        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("PackageName must be a single safe directory name", output)
        self.assertEqual("do not delete", victim_sentinel.read_text(encoding="utf-8"))

    def test_refuses_to_delete_unmarked_preexisting_stage(self):
        release_root = self.temp_root / "release-root"
        stage = release_root / "package"
        stage.mkdir(parents=True)
        sentinel = stage / "unrelated.txt"
        sentinel.write_text("unrelated user content", encoding="utf-8")

        result = self.run_release(release_root, "package")
        output = result.stdout + result.stderr

        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("Refusing to replace unowned release stage", output)
        self.assertEqual("unrelated user content", sentinel.read_text(encoding="utf-8"))

    def test_skip_zip_preserves_preexisting_zip(self):
        release_root = self.temp_root / "release-root"
        release_root.mkdir()
        zip_path = release_root / "package.zip"
        zip_path.write_bytes(b"unrelated zip content")

        result = self.run_release(release_root, "package")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertEqual(b"unrelated zip content", zip_path.read_bytes())

    def test_release_contains_install_and_locked_dependency_assets(self):
        release_root = self.temp_root / "release-root"
        stage = release_root / "package"

        result = self.run_release(release_root, "package")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        for relative_path in ("INSTALL.bat", "requirements.lock.txt", "setup_web.ps1"):
            self.assertTrue((stage / relative_path).is_file(), relative_path)

    def test_full_release_contains_and_can_import_refactored_nai_char_modules(self):
        release_root = self.temp_root / "release-root"
        stage = release_root / "package"

        result = self.run_release(release_root, "package")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertTrue((stage / "nai_char_modules" / "__init__.py").is_file())
        self.assertTrue((stage / "nai_char_modules" / "generation.py").is_file())
        self.assertTrue((stage / "pixiv_browser_source.py").is_file())
        self.assertTrue((stage / "pixiv_public_source.py").is_file())
        imported = subprocess.run(
            [
                "py",
                "-3.13",
                "-c",
                "import nai_char; print(nai_char.BUILD_MARKER)",
            ],
            cwd=stage,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(0, imported.returncode, imported.stdout + imported.stderr)
        self.assertEqual("refactored-nai-char", imported.stdout.strip())

    def test_full_release_contains_aitag_online_modules_pages_and_safe_defaults(self):
        release_root = self.temp_root / "release-root"
        stage = release_root / "package"

        result = self.run_release(release_root, "package")
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        for relative_path in FULL_REQUIRED_AITAG_FILES | {
            "web/tag-assets.html",
            "web/tag-assets.js",
            "web/tag-assets.css",
        }:
            self.assertTrue((stage / relative_path).is_file(), relative_path)
        config = __import__("json").loads(
            (stage / "config.json").read_text(encoding="utf-8-sig")
        )
        self.assertIs(config["aitag_online_enabled"], True)
        self.assertEqual(config["aitag_online_cache_ttl_sec"], 600)
        self.assertEqual(config["aitag_online_cache_max_bytes"], 64 * 1024 * 1024)
        self.assertEqual(config["aitag_online_timeout_sec"], 30)
        self.assertIs(config["legacy_aitag_crawler_enabled"], False)
        self.assertEqual(config["aitag_draft_ttl_sec"], 2592000)

        seed_manifest = json.loads(
            (stage / "data" / "seed_manifest.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(seed_manifest["generation_calls"], 0)
        self.assertEqual(
            {entry["path"] for entry in seed_manifest["files"]}, FULL_SEED_FILES
        )
        for entry in seed_manifest["files"]:
            asset = stage / entry["path"]
            self.assertTrue(asset.is_file(), entry["path"])
            self.assertEqual(entry["bytes"], asset.stat().st_size)
            self.assertEqual(entry["sha256"], hashlib.sha256(asset.read_bytes()).hexdigest())

        release_manifest = json.loads(
            (stage / "release_manifest.json").read_text(encoding="utf-8-sig")
        )
        self.assertEqual(release_manifest["schema_version"], 2)
        self.assertEqual(release_manifest["inventory_algorithm"], "sha256")
        inventory_paths = {entry["path"] for entry in release_manifest["inventory"]}
        self.assertIn("web/studio.js", inventory_paths)
        self.assertIn("web/plugins/char-swap/plugin.js", inventory_paths)
        actual_paths = {
            path.relative_to(stage).as_posix()
            for path in stage.rglob("*")
            if path.is_file() and path.name != "release_manifest.json"
        }
        self.assertEqual(inventory_paths, actual_paths)

    def test_late_validation_failure_does_not_publish_partial_stage(self):
        release_root = self.temp_root / "release-root"
        stage = release_root / "package"
        (self.fixture_project / "data" / "pixiv_launch.sample.json").write_text(
            '{"ai":{"provider":"must-not-ship","api_base":"","model":""}}',
            encoding="utf-8",
        )

        result = self.run_release(release_root, "package")
        output = result.stdout + result.stderr

        self.assertNotEqual(0, result.returncode, output)
        self.assertIn("must not include a default AI provider", output)
        self.assertFalse(stage.exists(), output)

    def test_zip_creation_handles_paths_with_spaces_and_contains_final_stage(self):
        release_root = self.temp_root / "release output"
        package_name = "gallery package"

        result = self.run_release_with_zip(release_root, package_name)
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertTrue((release_root / package_name).is_dir(), output)
        self.assertTrue((release_root / f"{package_name}.zip").is_file(), output)

    def test_release_and_zip_exclude_backup_variants_and_script_logs(self):
        web = self.fixture_project / "web"
        (web / "app.js.bak-20260811").write_text("private old source", encoding="utf-8")
        (web / "index.backup.html").write_text("private old page", encoding="utf-8")
        logs = self.fixture_project / "scripts" / "logs"
        logs.mkdir()
        (logs / "diagnostic.txt").write_text("local diagnostics", encoding="utf-8")
        release_root = self.temp_root / "clean release"
        package_name = "clean-package"

        result = self.run_release_with_zip(release_root, package_name)
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        stage = release_root / package_name
        self.assertFalse((stage / "web" / "app.js.bak-20260811").exists())
        self.assertFalse((stage / "web" / "index.backup.html").exists())
        self.assertFalse((stage / "scripts" / "logs").exists())
        with zipfile.ZipFile(release_root / f"{package_name}.zip") as archive:
            names = archive.namelist()
        self.assertFalse(any(".bak-" in name or ".backup." in name for name in names))
        self.assertFalse(any("/scripts/logs/" in name for name in names))

    def test_core_profile_uses_core_dependencies_and_excludes_full_suite(self):
        (self.fixture_project / "butler_service.py").write_text(
            "# full feature only\n", encoding="utf-8"
        )
        (self.fixture_project / "nai_director.py").write_text(
            "# full feature only\n", encoding="utf-8"
        )
        (self.fixture_project / "generation_jobs.py").write_text(
            "# full feature only\n", encoding="utf-8"
        )
        (self.fixture_project / "tests").mkdir()
        (self.fixture_project / "tests" / "test_private.py").write_text(
            "# must not ship\n", encoding="utf-8"
        )
        (self.fixture_project / "web" / "vendor" / "live2d-models").mkdir(
            parents=True
        )
        (self.fixture_project / "web" / "vendor" / "live2d-models" / "model.bin").write_bytes(
            b"restricted"
        )
        (self.fixture_project / "data" / "pixiv_accounts.local.json").write_text(
            '{"accounts":[{"refresh_token":"must-not-ship"}]}', encoding="utf-8"
        )
        (self.fixture_project / "data" / "images").mkdir()
        (self.fixture_project / "data" / "images" / "downloaded.png").write_bytes(
            b"downloaded image"
        )

        release_root = self.temp_root / "release-root"
        stage = release_root / "core-package"
        result = self.run_core_release(release_root, stage.name)
        output = result.stdout + result.stderr

        self.assertEqual(0, result.returncode, output)
        self.assertEqual(
            (self.fixture_project / "requirements.core.txt").read_text(encoding="utf-8"),
            (stage / "requirements.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (self.fixture_project / "requirements.core.lock.txt").read_text(encoding="utf-8"),
            (stage / "requirements.lock.txt").read_text(encoding="utf-8"),
        )
        self.assertFalse((stage / "requirements.core.txt").exists())
        self.assertFalse((stage / "tests").exists())
        for forbidden in ("butler_service.py", "nai_director.py", "generation_jobs.py"):
            self.assertFalse((stage / forbidden).exists(), forbidden)
        self.assertFalse((stage / "web" / "vendor" / "live2d-models").exists())
        self.assertFalse((stage / "data" / "pixiv_accounts.local.json").exists())
        for config_name in (
            "pixiv_launch.json",
            "pixiv_launch.sample.json",
            "post_pipeline.json",
            "post_pipeline.sample.json",
        ):
            self.assertFalse((stage / "data" / config_name).exists(), config_name)
        self.assertEqual(list((stage / "data" / "images").rglob("*")), [])
        for relative_path in (
            "gallery_maintenance.py",
            "gallery_snapshot.py",
            "nai_tag_index.py",
            "pixiv_browser_source.py",
            "pixiv_public_source.py",
            "routes/maintenance.py",
            "routes/nai_tags.py",
            "web/gallery-maintenance.js",
            "web/maintenance.html",
            "web/nai-tags.html",
            "web/nai-tags.js",
        ):
            self.assertTrue((stage / relative_path).is_file(), relative_path)


if __name__ == "__main__":
    unittest.main()

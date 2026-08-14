from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_primary_launcher_supports_bundled_runtime_and_first_run_bootstrap() -> None:
    launcher = _read("START_GALLERY.bat")
    assert 'if not defined GALLERY_PORT set "GALLERY_PORT=8797"' in launcher
    assert r"runtime\python.exe" in launcher
    assert "GALLERY_BOOTSTRAP" in launcher
    assert 'call "%~dp0INSTALL.bat"' in launcher
    assert "Automatic first-run setup failed" in launcher


def test_beginner_facing_launchers_delegate_to_the_safe_startup_path() -> None:
    for relative in ("ONE_CLICK_START.bat", "一键启动.bat"):
        wrapper = _read(relative)
        assert 'call "%~dp0START_GALLERY.bat" %*' in wrapper
        assert "exit /b %errorlevel%" in wrapper


def test_installer_has_non_recursive_bootstrap_mode() -> None:
    installer = _read("INSTALL.bat")
    assert "GALLERY_BOOTSTRAP" in installer
    assert "Bootstrap mode" in installer


def test_core_release_and_portable_builder_include_one_click_contract() -> None:
    release = _read("scripts/make_release.ps1")
    builder = _read("scripts/build_portable_runtime.ps1")
    assert '"ONE_CLICK_START.bat"' in release
    assert "[char]0x4E00" in release
    assert "$oneClickZhName" in release
    assert "requirements.lock.txt" in builder
    assert "runtime" in builder
    assert "server" in builder
    assert "PythonExe" in builder


def test_full_release_preserves_all_features_and_new_pixiv_nai_dependencies() -> None:
    release = _read("scripts/make_release.ps1")
    full_block = release.split("$fullRootFiles = @(", 1)[1].split(")\n$coreRootFiles", 1)[0]
    for relative in (
        "BACKUP_GALLERY.bat",
        "RESTORE_GALLERY.bat",
        "gallery_asset_store.py",
        "gallery_guard.py",
        "gallery_maintenance.py",
        "gallery_snapshot.py",
        "api_schemas.py",
        "network_safety.py",
        "nai_tag_index.py",
        "pixiv_nai_preflight.py",
        "static_asset_security.py",
        "pixiv_launch_config.py",
        "pixiv_ai_transport.py",
        "pixiv_launch_tags.py",
        "DISCLAIMER.md",
        "RESPONSIBLE_USE.md",
        "SECURITY.md",
    ):
        assert f'"{relative}"' in full_block
    assert 'Copy-DirRel "routes"' in release
    assert 'Copy-DirRel "web"' in release
    assert 'Copy-DirRel "docs"' in release
    assert "scripts\\import_bangdream_live2d.py" in release


def test_full_release_can_bundle_the_profile_aware_portable_runtime() -> None:
    release = _read("scripts/make_release.ps1")
    assert "BundlePythonRuntime is supported only for the Core release profile" not in release
    runtime_call = release.split('$runtimeBuilder = Join-Path $projectRoot "scripts\\build_portable_runtime.ps1"', 1)[1]
    assert "-Profile $Profile" in runtime_call
    assert '-BrowserMode "system"' in runtime_call


def test_release_builder_ignores_shell_python_functions() -> None:
    release = _read("scripts/make_release.ps1")
    assert "Get-Command python.exe -CommandType Application" in release
    assert "Get-Command python -ErrorAction" not in release


def test_private_test_bundle_can_explicitly_disable_only_the_content_filter() -> None:
    release = _read("scripts/make_release.ps1")
    assert "[switch]$AllowUnfilteredSampleContent" in release
    assert '"--allow-unfiltered-content"' in release


def test_sample_database_hash_is_finalized_once_before_isolated_server_import() -> None:
    release = _read("scripts/make_release.ps1")
    call = "Update-SampleDatabaseManifest -StagePath $stage"
    assert release.count(call) == 1
    verifier = "& $releasePython @verifyArgs"
    assert release.index(call) < release.index(verifier)
    verifier_source = _read("scripts/verify_release_stage.py")
    assert 'TemporaryDirectory(prefix="pixiv-nai-release-verify-")' in verifier_source
    assert 'isolated_config["data_dir"] = str(isolated_root)' in verifier_source
    assert "_seed_isolated_data_dir(stage, isolated_root)" in verifier_source
    assert "browser_mode" in release


def test_portable_builder_validates_full_profile_on_cpython_313_without_browser_download() -> None:
    builder = _read("scripts/build_portable_runtime.ps1")
    assert '[ValidateSet("core", "full")]' in builder
    assert '[ValidateSet("system")]' in builder
    assert '$minor -ne 13' in builder
    for module_name in ("aiosqlite", "langgraph", "orjson", "playwright", "sqlite_vec"):
        assert module_name in builder
    for route in (
        "/studio",
        "/generated",
        "/director",
        "/butler",
        "/pixiv",
        "/api/product/health",
        "/api/crawler/pixiv/task",
        "/api/maintenance/storage",
    ):
        assert route in builder
    assert 'browser_mode = "system_chrome_or_edge"' in builder
    assert "browser_runtime_included = $false" in builder
    assert "playwright install" not in builder.casefold()


def test_all_beginner_entrypoints_share_runtime_then_venv_then_global_selection() -> None:
    selector = _read("scripts/select_python_runtime.bat")
    runtime_pos = selector.index(r"runtime\python.exe")
    venv_pos = selector.index(r".venv\Scripts\python.exe")
    global_pos = selector.index("where python.exe")
    assert runtime_pos < venv_pos < global_pos
    assert 'set "GALLERY_PYTHON_EXE=' in selector
    assert 'set "GALLERY_PYTHON_MODE=' in selector

    for relative in (
        "START_GALLERY.bat",
        "BACKUP_GALLERY.bat",
        "RESTORE_GALLERY.bat",
        "Get-Pixiv-Token.bat",
    ):
        launcher = _read(relative)
        assert 'call "%~dp0scripts\\select_python_runtime.bat"' in launcher
        assert '"%GALLERY_PYTHON_EXE%"' in launcher

    release = _read("scripts/make_release.ps1")
    assert '"scripts\\select_python_runtime.bat"' in release


def test_runtime_selector_observably_prefers_runtime_then_venv() -> None:
    with tempfile.TemporaryDirectory() as temp:
        package = Path(temp) / "便携 gallery package"
        scripts = package / "scripts"
        scripts.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts" / "select_python_runtime.bat", scripts)
        runtime_python = package / "runtime" / "python.exe"
        venv_python = package / ".venv" / "Scripts" / "python.exe"
        runtime_python.parent.mkdir()
        venv_python.parent.mkdir(parents=True)
        runtime_python.touch()
        venv_python.touch()
        probe = package / "probe.bat"
        probe.write_text(
            '@echo off\n'
            'call "%~dp0scripts\\select_python_runtime.bat"\n'
            'echo EXE=%GALLERY_PYTHON_EXE%\n'
            'echo MODE=%GALLERY_PYTHON_MODE%\n',
            encoding="utf-8",
        )

        def run_probe() -> str:
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", str(probe)],
                cwd=package,
                capture_output=True,
                text=False,
                timeout=10,
            )
            decoded = []
            for encoding in ("utf-8", "mbcs", "oem"):
                try:
                    decoded.append(result.stdout.decode(encoding))
                except (LookupError, UnicodeDecodeError):
                    continue
            diagnostic = b"".join((result.stdout, result.stderr)).decode("utf-8", errors="replace")
            assert result.returncode == 0, diagnostic
            # Redirected cmd.exe output follows the active console code page;
            # CI can be UTF-8 even on a zh-CN system whose ANSI codec is GBK.
            return next(
                (text for text in decoded if str(package) in text),
                decoded[0] if decoded else diagnostic,
            )

        first = run_probe()
        assert str(runtime_python) in first
        assert "bundled portable runtime" in first

        runtime_python.unlink()
        second = run_probe()
        assert str(venv_python) in second
        assert "local environment" in second


def test_portable_builder_rejects_cpython_312_before_creating_runtime() -> None:
    candidates = list(
        (Path.home() / "AppData" / "Roaming" / "uv" / "python").glob(
            "cpython-3.12*-windows-*/python.exe"
        )
    )
    candidates.append(
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "python.exe"
    )
    python312 = next((str(path) for path in candidates if path.is_file()), "")
    if not python312:
        return
    with tempfile.TemporaryDirectory() as temp:
        package = Path(temp) / "full portable stage"
        package.mkdir()
        (package / ".pixiv-nai-release-stage").write_text(
            "pixiv-nai-gallery-release-v1\n", encoding="ascii"
        )
        (package / "requirements.lock.txt").write_text("", encoding="utf-8")
        (package / "server.py").write_text("app = None\n", encoding="utf-8")
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "build_portable_runtime.ps1"),
                "-PackageRoot",
                str(package),
                "-PythonExe",
                python312,
                "-Profile",
                "full",
                "-BrowserMode",
                "system",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert "requires CPython 3.13 x64" in output
        assert not (package / "runtime").exists()

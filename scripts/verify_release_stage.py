"""Package-level smoke gate for an assembled beginner release stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


FORBIDDEN_PRIVATE_NAMES = {
    "ai.local.json",
    "butler_state.db",
    "favorites.json",
    "generation_jobs.json",
    "nai_token.local.json",
    "pixiv.local.json",
    "pixiv_accounts.local.json",
    "pixiv_accounts.local.backup.json",
    "pixiv_nai_task.local.json",
    "pixiv_nai_state.local.json",
    "pixiv_nai_report.local.json",
    ".pixiv-credentials.lock",
    "user_prefs.json",
}
BACKUP_NAME_RE = re.compile(r"(?:^|[._-])(?:bak|backup)(?:[._-]|$)", re.IGNORECASE)

CORE_FORBIDDEN_PATH_TOKENS = {
    "aitag_core",
    "butler",
    "char_swap",
    "comfy",
    "director",
    "generated",
    "generation",
    "hiyori",
    "live2d",
    "remix",
    "studio",
    "tests",
}

CORE_REQUIRED_FILES = {
    "BUNDLE_NOTICE.txt",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "requirements.lock.txt",
    "requirements.txt",
    "ONE_CLICK_START.bat",
    "一键启动.bat",
    "gallery_maintenance.py",
    "gallery_snapshot.py",
    "nai_tag_index.py",
    "data/char_tag_groups.json",
    "data/char_tag_index.json",
    "data/danbooru_creature.json",
    "data/seed_manifest.json",
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
}

CORE_RESTRICTED_ASSET_TOKENS = {
    "hiyori",
    "live2d",
}

CORE_FORBIDDEN_CONFIG_PATHS = {
    "data/pixiv_launch.json",
    "data/pixiv_launch.sample.json",
    "data/post_pipeline.json",
    "data/post_pipeline.sample.json",
}

CORE_FORBIDDEN_DEPENDENCIES = {
    "gradio",
    "langgraph",
    "opencv-python",
    "opencv-python-headless",
    "playwright",
    "torch",
    "torchvision",
    "ultralytics",
    "ultralytics-thop",
}

FULL_REQUIRED_WEB_FILES = {
    "web/index.html",
    "web/butler.html",
    "web/director.html",
    "web/generated.html",
    "web/maintenance.html",
    "web/nai-tags.html",
    "web/ops.html",
    "web/pipeline.html",
    "web/pixiv.html",
    "web/progress.html",
    "web/references.html",
    "web/remix.html",
    "web/settings.html",
    "web/studio.html",
    "web/workspace.html",
    "web/app/workspace.js",
    "web/app/workspace.css",
    "web/studio.js",
    "web/tag-assets.html",
    "web/tag-assets.js",
    "web/tag-assets.css",
}

FULL_REQUIRED_AITAG_FILES = {
    "aitag_core/external.py",
    "aitag_core/online.py",
    "aitag_core/recipe.py",
    "aitag_core/studio.py",
    "aitag_core/qualification.py",
    "aitag_core/draft_store.py",
    "aitag_core/storage/http_cache.py",
    "routes/aitag.py",
    "web/tag-assets-model.js",
}

FULL_REQUIRED_ROUTE_PATHS = {
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
    "/api/plugin/char-swap/transform",
    "/api/butler/status",
    "/api/director/catalog",
    "/api/pixiv/accounts",
    "/api/nai/references",
    "/api/nai/aitag/status",
    "/api/nai/aitag/search",
    "/api/nai/aitag/favorites",
    "/api/nai/aitag/favorites/works",
    "/api/nai/aitag/favorites/{work_id}/toggle",
    "/api/nai/aitag/work/{work_id}",
    "/api/nai/aitag/work/{work_id}/characters",
    "/api/nai/aitag/work/{work_id}/apply",
    "/api/nai/aitag/work/{work_id}/draft",
    "/api/nai/aitag/drafts/latest/restore",
    "/api/nai/aitag/drafts/{draft_id}",
    "/api/nai/aitag/import",
    "/api/nai/aitag/cache/clear",
    "/api/settings/status",
    "/api/pipeline/status",
    "/api/product/health",
    "/api/crawler/pixiv/task",
    "/api/crawler/pixiv/report",
    "/api/nai-tags",
    "/api/maintenance/storage",
}

FULL_SEED_FILES = {
    "data/ark_char_library.json",
    "data/butler_catalog.json",
    "data/char_presets.json",
    "data/char_tag_index.json",
    "data/danbooru_arknights.json",
    "data/danbooru_creature.json",
    "data/danbooru_recognition.json",
    "data/danbooru_style_tags.json",
    "data/director_catalog.json",
    "data/pixiv_upload_selectors.json",
}

CORE_SEED_FILES = {
    "data/char_tag_index.json",
    "data/danbooru_creature.json",
}

FULL_WEB_DEPENDENCY_ROOTS = {
    "web/studio.html",
    "web/plugins/char-swap/plugin.js",
}

CORE_CONTENT_SCAN_SUFFIXES = {".bat", ".css", ".html", ".js", ".ps1", ".py", ".vbs"}
CORE_FORBIDDEN_CONTENT_PATTERNS = {
    "butler": re.compile(r"\bbutler\b", re.IGNORECASE),
    "comfy": re.compile(r"\bcomfy(?:ui)?\b", re.IGNORECASE),
    "director": re.compile(r"\bdirector\b", re.IGNORECASE),
    "live2d": re.compile(r"\b(?:live2d|hiyori)\b", re.IGNORECASE),
    "sd-runtime": re.compile(r"\bstable\s*diffusion\b|\bsd[_-](?:model|vae|lora)\b", re.IGNORECASE),
    "full-suite-route": re.compile(
        r"[\"'`](?:/api)?/(?:butler|director|generated|remix|studio)(?:[/\"'`?]|$)",
        re.IGNORECASE,
    ),
    "generation-queue": re.compile(
        r"\bgeneration_jobs\b|\bgeneration[_-]queue\b|生成队列",
        re.IGNORECASE,
    ),
}


def _requirement_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _requirement_name(line: str) -> str:
    return re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].strip().casefold()


def _verify_core_dependencies(stage: Path) -> None:
    requirements = _requirement_lines(stage / "requirements.txt")
    lock_lines = _requirement_lines(stage / "requirements.lock.txt")
    names = {_requirement_name(line) for line in requirements + lock_lines}
    heavy = sorted(names & CORE_FORBIDDEN_DEPENDENCIES)
    unpinned = [line for line in lock_lines if "==" not in line]
    if heavy or unpinned:
        raise RuntimeError(
            "Core dependency boundary failed: "
            f"heavy={heavy}, unpinned={unpinned[:20]}"
        )


def _verify_core_content(stage: Path) -> None:
    hits: list[str] = []
    for path in stage.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in CORE_CONTENT_SCAN_SUFFIXES:
            continue
        relative = path.relative_to(stage)
        if relative.parts and relative.parts[0].casefold() == "runtime":
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        for label, pattern in CORE_FORBIDDEN_CONTENT_PATTERNS.items():
            # The NAI admission parser must recognize and reject foreign workflow
            # metadata.  This is a negative detector, not a shipped feature.
            if relative.as_posix() == "nai_image_metadata.py" and label == "comfy":
                continue
            if pattern.search(content):
                hits.append(f"{relative}:{label}")
    if hits:
        raise RuntimeError(f"Core release contains excluded feature reference: {hits[:20]}")


def _release_manifest(stage: Path) -> dict[str, object]:
    manifest_path = stage / "release_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("release_manifest.json is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or int(manifest.get("schema_version") or 0) != 2:
        raise RuntimeError("release manifest schema_version must be 2")
    if str(manifest.get("inventory_algorithm") or "").casefold() != "sha256":
        raise RuntimeError("release manifest inventory_algorithm must be sha256")
    return manifest


def _release_profile(manifest: dict[str, object]) -> str:
    profile = str(manifest.get("release_profile") or "").strip().casefold()
    if profile not in {"full", "core"}:
        raise RuntimeError(f"unsupported release profile: {profile!r}")
    return profile


def _verify_release_inventory(stage: Path, manifest: dict[str, object]) -> None:
    raw_inventory = manifest.get("inventory")
    if not isinstance(raw_inventory, list):
        raise RuntimeError("release manifest inventory must be a list")
    declared: dict[str, tuple[int, str]] = {}
    for raw_entry in raw_inventory:
        if not isinstance(raw_entry, dict):
            raise RuntimeError("release manifest inventory entry must be an object")
        relative = str(raw_entry.get("path") or "")
        normalized = posixpath.normpath(relative.replace("\\", "/"))
        if (
            not relative
            or relative != normalized
            or relative.startswith("/")
            or normalized == ".."
            or normalized.startswith("../")
            or relative == "release_manifest.json"
            or relative in declared
        ):
            raise RuntimeError(f"invalid or duplicate release inventory path: {relative!r}")
        declared[relative] = (
            int(raw_entry.get("bytes") or 0),
            str(raw_entry.get("sha256") or "").casefold(),
        )
    stage_root = Path(os.path.realpath(stage))
    actual = {
        Path(os.path.realpath(path)).relative_to(stage_root).as_posix(): path
        for path in stage.rglob("*")
        if path.is_file() and path.name != "release_manifest.json"
    }
    missing = sorted(set(declared) - set(actual))
    extra = sorted(set(actual) - set(declared))
    if missing or extra:
        raise RuntimeError(
            f"release manifest inventory mismatch: missing={missing[:20]}, extra={extra[:20]}"
        )
    mismatches: list[str] = []
    total_bytes = 0
    for relative, path in actual.items():
        expected_bytes, expected_hash = declared[relative]
        actual_bytes = path.stat().st_size
        total_bytes += actual_bytes
        if (
            expected_bytes != actual_bytes
            or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
            or expected_hash != _sha256(path)
        ):
            mismatches.append(relative)
    if mismatches:
        raise RuntimeError(f"release manifest hash/size mismatch: {mismatches[:20]}")
    if int(manifest.get("file_count") or -1) != len(actual):
        raise RuntimeError("release manifest file_count does not match inventory")
    if int(manifest.get("bytes") or -1) != total_bytes:
        raise RuntimeError("release manifest bytes does not match inventory")


def _verify_seed_assets(stage: Path, profile: str) -> None:
    manifest_path = stage / "data" / "seed_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("starter-library manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if int(manifest.get("schema_version") or 0) != 1:
        raise RuntimeError("starter-library manifest schema_version must be 1")
    if str(manifest.get("release_profile") or "").casefold() != profile:
        raise RuntimeError("starter-library manifest release profile mismatch")
    if int(manifest.get("generation_calls", -1)) != 0:
        raise RuntimeError("starter-library manifest must declare generation_calls=0")
    required = CORE_SEED_FILES if profile == "core" else FULL_SEED_FILES
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise RuntimeError("starter-library manifest files must be a list")
    declared = {str(entry.get("path") or ""): entry for entry in entries if isinstance(entry, dict)}
    if set(declared) != required:
        raise RuntimeError(
            f"starter-library inventory mismatch: expected={sorted(required)}, actual={sorted(declared)}"
        )
    for relative, entry in declared.items():
        path = stage / Path(relative)
        if not path.is_file():
            raise FileNotFoundError(f"starter-library asset is missing: {relative}")
        if int(entry.get("bytes") or 0) != path.stat().st_size:
            raise RuntimeError(f"starter-library size mismatch: {relative}")
        if str(entry.get("sha256") or "").casefold() != _sha256(path):
            raise RuntimeError(f"starter-library hash mismatch: {relative}")


def _local_web_dependency(source: str, specifier: str) -> str | None:
    clean = specifier.split("?", 1)[0].split("#", 1)[0].strip()
    if not clean or clean.startswith(("http://", "https://", "data:", "//")):
        return None
    if clean.startswith("/assets/"):
        candidate = "web/" + clean[len("/assets/"):]
    elif clean.startswith("./") or clean.startswith("../"):
        candidate = posixpath.join(posixpath.dirname(source), clean)
    else:
        return None
    normalized = posixpath.normpath(candidate)
    if normalized == ".." or normalized.startswith("../"):
        raise RuntimeError(f"web dependency escapes release stage: {source} -> {specifier}")
    return normalized


def _verify_full_web_dependency_closure(stage: Path) -> None:
    pending = list(FULL_WEB_DEPENDENCY_ROOTS)
    visited: set[str] = set()
    missing: list[str] = []
    while pending:
        relative = pending.pop()
        if relative in visited:
            continue
        visited.add(relative)
        path = stage / Path(relative)
        if not path.is_file():
            missing.append(relative)
            continue
        if path.suffix.casefold() not in {".html", ".js", ".mjs"}:
            continue
        content = path.read_text(encoding="utf-8-sig")
        specifiers: list[str] = []
        if path.suffix.casefold() == ".html":
            specifiers.extend(
                re.findall(r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", content, re.IGNORECASE)
            )
        else:
            specifiers.extend(
                re.findall(
                    r"\b(?:import|export)\s+(?:[^;]*?\s+from\s+)?[\"']([^\"']+)[\"']",
                    content,
                    re.MULTILINE,
                )
            )
            specifiers.extend(
                re.findall(r"\bimport\s*\(\s*[\"']([^\"']+)[\"']", content)
            )
        for specifier in specifiers:
            dependency = _local_web_dependency(relative, specifier)
            if dependency is not None and dependency not in visited:
                pending.append(dependency)
    if missing:
        raise FileNotFoundError(f"Full release web dependency is missing: {sorted(missing)}")


def _seed_isolated_data_dir(stage: Path, isolated: Path) -> None:
    """Copy packaged seed JSON into the isolated data_dir used for import probes."""
    isolated.mkdir(parents=True, exist_ok=True)
    source = stage / "data"
    if not source.is_dir():
        return
    for path in source.iterdir():
        if not path.is_file() or path.suffix.casefold() != ".json":
            continue
        name = path.name.casefold()
        if name in FORBIDDEN_PRIVATE_NAMES or name.endswith(".local.json"):
            continue
        shutil.copy2(path, isolated / path.name)


def _import_server_route_paths(stage: Path, config: dict[str, object]) -> set[str]:
    config_path = stage / "config.json"
    original_config_bytes = config_path.read_bytes()
    probe = (
        "import json, server; "
        "print('__RELEASE_ROUTES__=' + json.dumps("
        "sorted({getattr(route, 'path', '') for route in server.app.routes})))"
    )
    try:
        with tempfile.TemporaryDirectory(prefix="pixiv-nai-release-verify-") as runtime_data:
            isolated_root = Path(runtime_data)
            _seed_isolated_data_dir(stage, isolated_root)
            isolated_config = dict(config)
            isolated_config["data_dir"] = str(isolated_root)
            config_path.write_text(
                json.dumps(isolated_config, ensure_ascii=False), encoding="utf-8"
            )
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            completed = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=stage,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(f"release server import failed in isolated process: {detail}")
            marker = next(
                (
                    line.removeprefix("__RELEASE_ROUTES__=")
                    for line in completed.stdout.splitlines()
                    if line.startswith("__RELEASE_ROUTES__=")
                ),
                "",
            )
            if not marker:
                raise RuntimeError("release server route probe did not return a route inventory")
            return {str(path) for path in json.loads(marker)}
    finally:
        config_path.write_bytes(original_config_bytes)


def _verify_full_web_surface(stage: Path) -> None:
    missing = sorted(
        relative
        for relative in FULL_REQUIRED_WEB_FILES
        if not (stage / Path(relative)).is_file()
    )
    if missing:
        raise FileNotFoundError(f"Full release page is missing: {missing}")


def _verify_full_aitag_surface(stage: Path, config: dict[str, object]) -> None:
    missing = sorted(
        relative
        for relative in FULL_REQUIRED_AITAG_FILES
        if not (stage / Path(relative)).is_file()
    )
    if missing:
        raise FileNotFoundError(f"Full release AITag online module is missing: {missing}")
    expected = {
        "aitag_online_enabled": True,
        "aitag_online_cache_ttl_sec": 600,
        "aitag_online_cache_max_bytes": 64 * 1024 * 1024,
        "aitag_online_timeout_sec": 30,
        "aitag_draft_ttl_sec": 2592000,
        "legacy_aitag_crawler_enabled": False,
    }
    actual = {key: config.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError(
            f"Full release AITag online defaults are invalid: {actual}"
        )


def _verify_core_boundary(stage: Path) -> None:
    image_root = stage / "data" / "images"
    downloaded_images = [
        str(path.relative_to(stage))
        for path in image_root.rglob("*")
        if path.is_file()
    ] if image_root.is_dir() else []
    if downloaded_images:
        raise RuntimeError(
            f"Core release contains downloaded image data: {downloaded_images[:20]}"
        )
    forbidden_configs = sorted(
        relative for relative in CORE_FORBIDDEN_CONFIG_PATHS if (stage / relative).is_file()
    )
    if forbidden_configs:
        raise RuntimeError(f"Core release contains full-suite configuration: {forbidden_configs}")
    forbidden: list[str] = []
    restricted_assets: list[str] = []
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(stage)
        if relative.parts and relative.parts[0].casefold() == "runtime":
            continue
        tokens = {part.casefold() for part in relative.parts}
        stem_tokens = {
            token
            for part in relative.parts
            for token in part.casefold().replace("-", "_").replace(".", "_").split("_")
        }
        if stem_tokens & CORE_RESTRICTED_ASSET_TOKENS:
            restricted_assets.append(str(relative))
        if tokens & CORE_FORBIDDEN_PATH_TOKENS or stem_tokens & CORE_FORBIDDEN_PATH_TOKENS:
            forbidden.append(str(relative))
    if restricted_assets:
        raise RuntimeError(
            f"Core release contains restricted asset files: {restricted_assets[:20]}"
        )
    if forbidden:
        raise RuntimeError(f"Core-forbidden feature files found: {forbidden[:20]}")
    missing = sorted(name for name in CORE_REQUIRED_FILES if not (stage / name).is_file())
    if missing:
        raise FileNotFoundError(f"Core release file is missing: {missing}")
    _verify_core_dependencies(stage)
    _verify_core_content(stage)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(
    stage: Path,
    *,
    require_sample: bool,
    import_server: bool = True,
) -> dict[str, int | str | bool]:
    stage = stage.resolve()
    if not stage.is_dir():
        raise FileNotFoundError(f"release stage not found: {stage}")
    release_manifest = _release_manifest(stage)
    profile = _release_profile(release_manifest)
    if profile == "core":
        _verify_core_boundary(stage)
    _verify_seed_assets(stage, profile)
    forbidden = [
        str(path.relative_to(stage))
        for path in stage.rglob("*")
        if path.is_file() and path.name.casefold() in FORBIDDEN_PRIVATE_NAMES
    ]
    if forbidden:
        raise RuntimeError(f"private runtime files found in release: {forbidden}")
    backup_artifacts = [
        str(path.relative_to(stage))
        for path in stage.rglob("*")
        # 相对路径任一段命中备份命名（含备份目录内的正常命名文件）都算违规
        if path.is_file()
        and any(
            BACKUP_NAME_RE.search(part)
            for part in path.relative_to(stage).parts
        )
    ]
    scripts_logs = stage / "scripts" / "logs"
    if scripts_logs.exists():
        backup_artifacts.append(str(scripts_logs.relative_to(stage)))
    if backup_artifacts:
        raise RuntimeError(f"backup or diagnostic artifacts found in release: {backup_artifacts}")
    runtime_residue = [
        str(path.relative_to(stage))
        for path in stage.rglob("*")
        if (
            path.name == "__pycache__"
            or (path.is_file() and path.suffix.lower() in {".pyc", ".db-wal", ".db-shm"})
            or (path.is_dir() and path == stage / "data" / "cache")
        )
    ]
    if runtime_residue:
        raise RuntimeError(f"runtime cache files found in release: {runtime_residue}")

    config = json.loads((stage / "config.json").read_text(encoding="utf-8"))
    if str(config.get("base_url") or "") or str(config.get("cdn_url") or ""):
        raise RuntimeError("release must not depend on the legacy upstream or CDN")
    if bool(config.get("legacy_aitag_crawler_enabled", False)):
        raise RuntimeError("legacy upstream crawler must be disabled")
    if profile == "full":
        _verify_full_aitag_surface(stage, config)
        _verify_full_web_surface(stage)
        _verify_full_web_dependency_closure(stage)
    for module_name in (
        "nai_prompt_tags.py",
        "pixiv_nai_source.py",
        "pixiv_nai_intake.py",
        "pixiv_nai_crawler.py",
    ):
        if not (stage / module_name).is_file():
            raise FileNotFoundError(f"release intake module is missing: {module_name}")

    db_path = stage / "data" / "aitag.db"
    if require_sample and not db_path.is_file():
        raise FileNotFoundError("sample database is missing")
    works = 0
    images = 0
    if db_path.is_file():
        connection = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro&immutable=1",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"release database integrity check failed: {integrity}")
            works = int(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])
            images = int(connection.execute("SELECT COUNT(*) FROM work_images").fetchone()[0])
            missing = []
            assets: list[Path] = []
            for row in connection.execute(
                "SELECT work_id, page_index, local_path FROM work_images WHERE downloaded = 1"
            ):
                local_path = str(row["local_path"] or "")
                candidates = [
                    stage / "data" / "images" / local_path,
                    stage / "data" / local_path,
                ]
                asset = next((path for path in candidates if path.is_file()), None)
                if not local_path or asset is None:
                    missing.append(f"{row['work_id']}:{row['page_index']}:{local_path}")
                else:
                    assets.append(asset)
            if missing:
                raise RuntimeError(f"release database references missing images: {missing[:5]}")
            if require_sample:
                non_nai = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM works WHERE LOWER(TRIM(COALESCE(ai_type, ''))) <> 'nai'"
                    ).fetchone()[0]
                )
                non_pixiv = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM works "
                        "WHERE COALESCE(json_extract(list_json, '$.source'), '') <> 'pixiv-direct'"
                    ).fetchone()[0]
                )
                if non_nai or non_pixiv:
                    raise RuntimeError(
                        "release sample may contain only direct-Pixiv, verified NAI works"
                    )
        finally:
            connection.close()
        if require_sample:
            if str(stage) not in sys.path:
                sys.path.insert(0, str(stage))
            from nai_image_metadata import parse_nai_image

            invalid_assets = [str(path) for path in assets if not parse_nai_image(path).accepted]
            if invalid_assets:
                raise RuntimeError(
                    f"release sample contains non-NAI final assets: {invalid_assets[:5]}"
                )
    if require_sample and (works <= 0 or images <= 0):
        raise RuntimeError("release sample must contain works and images")

    sample_manifest_path = stage / "data" / "sample_manifest.json"
    if require_sample and not sample_manifest_path.is_file():
        raise FileNotFoundError("sample manifest is missing")
    if sample_manifest_path.is_file() and db_path.is_file():
        sample_manifest = json.loads(
            sample_manifest_path.read_text(encoding="utf-8-sig")
        )
        expected_database_hash = str(
            sample_manifest.get("database_sha256") or ""
        ).lower()
        actual_database_hash = _sha256(db_path)
        if expected_database_hash != actual_database_hash:
            raise RuntimeError(
                "sample manifest database hash does not match packaged database"
            )

    route_paths: set[str] = set()
    if import_server:
        route_paths = _import_server_route_paths(stage, config)
        required_routes = {
            "/",
            "/api/config",
            "/api/crawler/pixiv/task",
            "/api/crawler/pixiv/report",
        }
        if profile == "core":
            required_routes.update({"/api/nai-tags", "/nai-tags"})
        else:
            required_routes.update(FULL_REQUIRED_ROUTE_PATHS)
        missing_routes = sorted(required_routes - route_paths)
        if missing_routes:
            raise RuntimeError(f"release server is missing routes: {missing_routes}")

    _verify_release_inventory(stage, release_manifest)

    return {
        "ok": True,
        "works": works,
        "images": images,
        "routes": len(route_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", type=Path)
    parser.add_argument("--allow-empty-sample", action="store_true")
    parser.add_argument("--skip-server-import", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                args.stage,
                require_sample=not args.allow_empty_sample,
                import_server=not args.skip_server_import,
            ),
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

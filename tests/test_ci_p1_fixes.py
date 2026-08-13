"""Regressions for the c5d9a57 CI follow-up and the 2026-08-13 P1 list."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

from nai.constants import PROVIDER_NOVELAI, PROVIDER_UNKNOWN
from paths import canonical_path, path_is_within
from scripts.product_quality_gate import collect_findings


ROOT = Path(__file__).resolve().parents[1]


def _ci_windows_temp(*parts: str, short: bool = False) -> Path:
    profile = "RUNNER~1" if short else "runneradmin"
    return Path("C:/Users") / profile / "AppData" / "Local" / "Temp" / Path(*parts)


def test_canonical_path_equates_short_and_long_windows_forms(monkeypatch) -> None:
    long_form = str(_ci_windows_temp("t", "data", "images"))
    short_form = str(_ci_windows_temp("t", "data", "images", short=True))
    long_child = str(_ci_windows_temp("t", "data", "images", "NAI", "9", "fallback_p1.webp"))
    short_child = str(_ci_windows_temp("t", "data", "images", "NAI", "9", "fallback_p1.webp", short=True))
    mapping = {
        os.path.normpath(short_form): long_form,
        os.path.normpath(long_form): long_form,
        os.path.normpath(long_child): os.path.normpath(long_child),
        os.path.normpath(short_child): os.path.normpath(long_child),
    }

    def fake_realpath(path: str | os.PathLike[str]) -> str:
        key = os.path.normpath(os.fspath(path))
        return mapping.get(key, key)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)
    parent = Path(short_form)
    child = Path(long_child)
    assert canonical_path(parent) == canonical_path(Path(long_form))
    assert path_is_within(child, parent)


def test_preview_local_path_uses_canonical_containment(tmp_path: Path) -> None:
    from crawler import preview_local_path

    images = tmp_path / "images"
    destination = preview_local_path(
        images,
        {"image_type": "NAI", "author_id": "9", "file_name": "fallback_p1.webp"},
    )
    assert path_is_within(destination, images)
    assert destination.name == "fallback_p1.webp"


def test_probe_provider_uses_httpx_not_missing_api_module() -> None:
    source = (ROOT / "nai" / "tokens.py").read_text(encoding="utf-8")
    assert "import api.httpx" not in source

    class _Resp:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    with patch("nai.tokens.httpx.get", return_value=_Resp(200)) as get:
        from nai.tokens import _probe_provider

        assert _probe_provider("opaque-token") == PROVIDER_NOVELAI
        get.assert_called_once()


def test_probe_provider_unknown_when_httpx_unavailable() -> None:
    with patch("nai.tokens.httpx.get", side_effect=RuntimeError("offline")), patch(
        "nai.tokens.httpx.post", side_effect=RuntimeError("offline")
    ):
        from nai.tokens import _probe_provider

        assert _probe_provider("opaque-token") == PROVIDER_UNKNOWN


def test_quality_gate_does_not_require_gitignored_work_notes() -> None:
    source = (ROOT / "scripts" / "product_quality_gate.py").read_text(encoding="utf-8")
    assert '"task_plan.md"' not in source
    assert '"findings.md"' not in source
    result = collect_findings(ROOT)
    assert not any("task_plan.md" in item for item in result["p0"])
    assert not any("findings.md" in item for item in result["p0"])


def test_release_script_hashes_without_get_filehash() -> None:
    script = (ROOT / "scripts" / "make_release.ps1").read_text(encoding="utf-8")
    assert "function Get-Sha256Hex" in script
    assert "Get-FileHash" not in script
    portable = (ROOT / "scripts" / "build_portable_runtime.ps1").read_text(encoding="utf-8")
    assert "function Get-Sha256Hex" in portable
    assert "Get-FileHash" not in portable


def test_release_inventory_expands_83_before_substring() -> None:
    script = (ROOT / "scripts" / "make_release.ps1").read_text(encoding="utf-8")
    assert "Substring($stage.Length)" not in script
    assert "function ConvertTo-ExistingLongPath" in script
    assert "function Get-InventoryRelativePath" in script
    verifier = (ROOT / "scripts" / "verify_release_stage.py").read_text(encoding="utf-8")
    assert "os.path.realpath(stage)" in verifier


def test_verify_inventory_matches_when_stage_is_83_short_path(tmp_path: Path) -> None:
    if os.name != "nt":
        return
    from scripts.verify_release_stage import _verify_release_inventory

    stage = tmp_path / "stage"
    target = stage / "web" / "LICENSE"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"ok\n")
    digest = hashlib.sha256(b"ok\n").hexdigest()
    manifest = {
        "inventory_algorithm": "sha256",
        "file_count": 1,
        "bytes": 3,
        "inventory": [{"path": "web/LICENSE", "bytes": 3, "sha256": digest}],
    }
    import ctypes

    get_short = ctypes.windll.kernel32.GetShortPathNameW
    get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    get_short.restype = ctypes.c_uint
    buf = ctypes.create_unicode_buffer(32768)
    n = get_short(str(stage), buf, 32768)
    short_stage = Path(buf.value) if n else stage
    _verify_release_inventory(short_stage, manifest)


def test_unexpected_batch_exception_is_unknown_lane() -> None:
    source = (ROOT / "nai_batch.py").read_text(encoding="utf-8")
    run_batch = source.split("async def _run_batch", 1)[1].split("\ndef _launch_job", 1)[0]
    assert 'status="unknown"' in run_batch
    assert "这次可能已扣费，任务异常中断" in run_batch


def test_butler_poll_loops_check_cancel_and_timeout() -> None:
    source = (ROOT / "butler" / "workflow_executors.py").read_text(encoding="utf-8")
    assert source.count("cancel_requested") >= 3
    assert source.count("_poll_timed_out") >= 3
    assert "cancel_pipeline" in source
    from butler.workflow_helpers import POLL_WALL_CLOCK_TIMEOUT_SEC, _poll_timed_out
    import time

    assert POLL_WALL_CLOCK_TIMEOUT_SEC >= 60
    assert _poll_timed_out(time.monotonic()) is False


def test_pipeline_exposes_cancel() -> None:
    from post_pipeline import cancel_pipeline, pipeline_status

    result = cancel_pipeline()
    assert "ok" in result
    status = pipeline_status()
    assert "status" in status


def test_reader_connections_set_busy_timeout() -> None:
    source = (ROOT / "db.py").read_text(encoding="utf-8")
    assert source.count("PRAGMA busy_timeout=30000") >= 2


def test_nai_jobs_and_planning_drop_god_module_import_headers() -> None:
    jobs = (ROOT / "nai" / "jobs.py").read_text(encoding="utf-8")
    planning = (ROOT / "butler" / "planning.py").read_text(encoding="utf-8")
    assert "from PIL import Image" not in jobs
    assert "from pixiv_launch import chat_json" not in planning
    assert "from nai.facade import api" in jobs
    assert "from butler.service_api import api" in planning

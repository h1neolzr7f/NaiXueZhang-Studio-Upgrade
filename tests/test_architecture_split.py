from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import butler_service
import nai_api
from butler.normalize import normalize_action as normalize_impl
from nai.generate import generate_image as generate_impl
from nai.tokens import _check_one_token_entry


ROOT = Path(__file__).resolve().parents[1]


def test_nai_facade_reexports_package_implementation() -> None:
    assert nai_api.generate_image is generate_impl
    assert nai_api._check_one_token_entry is _check_one_token_entry
    assert (ROOT / "nai" / "tokens.py").is_file()
    assert (ROOT / "nai" / "generate.py").is_file()
    assert (ROOT / "nai" / "director.py").is_file()


def test_nai_facade_patches_reach_internal_calls() -> None:
    entry = {"id": "slot-a", "token": "pst-test", "provider": "novelai", "enabled": True}
    with patch.object(nai_api, "_token_check_request", return_value=(403, "account forbidden")), patch.object(
        nai_api, "_remove_token_entry", return_value=True
    ) as remove:
        nai_api._check_one_token_entry(entry, remove_bad=True)
    remove.assert_called()


def test_butler_facade_reexports_package_implementation() -> None:
    assert butler_service.normalize_action is normalize_impl
    assert (ROOT / "butler" / "planning.py").is_file()
    assert (ROOT / "butler" / "execute.py").is_file()
    assert (ROOT / "butler" / "normalize.py").is_file()
    assert (ROOT / "butler" / "workflow_helpers.py").is_file()
    assert (ROOT / "butler" / "workflow_runtime.py").is_file()
    assert (ROOT / "butler" / "workflow_executors.py").is_file()
    workflow = (ROOT / "butler" / "workflow.py").read_text(encoding="utf-8")
    runtime = (ROOT / "butler" / "workflow_runtime.py").read_text(encoding="utf-8")
    executors = (ROOT / "butler" / "workflow_executors.py").read_text(encoding="utf-8")
    assert "class ButlerWorkflowRuntime" not in workflow
    assert "from .workflow_runtime import ButlerWorkflowRuntime" in workflow
    assert "from .workflow_executors import ButlerWorkflowExecutors" in runtime
    assert "class ButlerWorkflowRuntime(ButlerWorkflowExecutors)" in runtime
    assert "async def _execute_director" not in runtime
    assert "async def _execute_batch" not in runtime
    assert "class ButlerWorkflowExecutors" in executors
    assert "async def _execute_director" in executors


def test_release_script_copies_nai_package() -> None:
    script = (ROOT / "scripts" / "make_release.ps1").read_text(encoding="utf-8")
    assert 'Copy-DirRel "nai"' in script
    assert 'Copy-DirRel "butler"' in script


def test_nai_paths_resolve_through_data_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(nai_api, "data_dir", lambda: tmp_path)
    assert nai_api.DATA_DIR == tmp_path
    assert nai_api.TOKEN_PATH == tmp_path / "nai_token.local.json"
    assert nai_api.GENERATED_DIR == tmp_path / "generated"

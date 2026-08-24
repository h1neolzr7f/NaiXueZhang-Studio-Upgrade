from __future__ import annotations

from unittest.mock import patch

from tests.asgi_client import TestClient

import server


client = TestClient(server.app)


def test_transform_route_passes_through_the_domain_result() -> None:
    transformed = {
        "ok": True,
        "patched_comment": {"prompt": "scene"},
        "chars": [],
        "replaced_indices": [0],
    }
    request = {"target_work_id": 1, "target_char_index": 0}
    with patch("routes.char_swap.transform", return_value=transformed) as transform:
        response = client.post("/api/plugin/char-swap/transform", json=request)

    assert response.status_code == 200
    assert response.json() == transformed
    transform.assert_called_once_with(request)


def test_transform_route_preserves_validation_and_internal_error_shapes() -> None:
    with patch("routes.char_swap.transform", side_effect=ValueError("invalid slot")):
        validation = client.post("/api/plugin/char-swap/transform", json={})
    with patch("routes.char_swap.transform", side_effect=RuntimeError("broken")):
        internal = client.post("/api/plugin/char-swap/transform", json={})

    assert validation.status_code == 400
    assert validation.json() == {"detail": "invalid slot"}
    assert internal.status_code == 500
    assert set(internal.json()) == {"detail"}
    assert "broken" in internal.json()["detail"]


def test_transform_support_routes_pass_through_their_domain_shapes() -> None:
    cases = [
        ("/sanitize", "sanitize_payload", {"ok": True, "removed": []}),
        ("/style", "apply_style_payload", {"ok": True, "style_slots": []}),
        ("/batch/preview", "batch_preview", {"ok": True, "items": []}),
    ]
    request = {"patched_comment": {"prompt": "scene"}}
    for suffix, function_name, expected in cases:
        with patch(f"routes.char_swap.{function_name}", return_value=expected) as call:
            response = client.post(f"/api/plugin/char-swap{suffix}", json=request)
        assert response.status_code == 200
        assert response.json() == expected
        call.assert_called_once_with(request)


def test_batch_run_defaults_to_free_guarded_generation() -> None:
    started = {
        "ok": True,
        "task_id": "job-1",
        "batch": {"task_id": "job-1", "status": "queued"},
    }
    request = {"targets": [{"work_id": 1}], "recipe": {"mode": "replace"}}
    with patch("routes.char_swap.start_batch", return_value=started) as start:
        response = client.post("/api/plugin/char-swap/batch/run", json=request)

    assert response.status_code == 200
    assert response.json() == started
    start.assert_called_once_with(
        [{"work_id": 1}],
        {"mode": "replace"},
        force_free=True,
        generate=True,
        preview_only=False,
    )


def test_batch_preview_only_is_explicit_and_never_changes_into_generation() -> None:
    started = {
        "ok": True,
        "task_id": "preview-1",
        "batch": {
            "task_id": "preview-1",
            "status": "queued",
            "generate": False,
            "preview_only": True,
        },
    }
    request = {
        "targets": [{"work_id": 1}],
        "recipe": {},
        "force_free": False,
        "generate": True,
        "preview_only": True,
    }
    with patch("routes.char_swap.start_batch", return_value=started) as start:
        response = client.post("/api/plugin/char-swap/batch/run", json=request)

    assert response.status_code == 200
    assert response.json() == started
    start.assert_called_once_with(
        [{"work_id": 1}],
        {},
        force_free=False,
        generate=True,
        preview_only=True,
    )


def test_batch_status_wraps_the_stable_generation_job_shape() -> None:
    job = {
        "id": "job-1",
        "task_id": "job-1",
        "status": "running",
        "terminal": False,
        "generate": True,
        "preview_only": False,
        "needs_review": False,
    }
    with patch("routes.char_swap.batch_status", return_value=job):
        response = client.get("/api/plugin/char-swap/batch/status?task_id=job-1")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "batch": job}


def test_retry_never_replays_a_billing_uncertain_job() -> None:
    blocked = {
        "ok": False,
        "error": "needs_review",
        "message": "billing result needs manual review",
        "task_id": "job-1",
    }
    with patch("routes.char_swap.retry_batch", return_value=blocked):
        response = client.post("/api/plugin/char-swap/batch/retry?task_id=job-1")

    assert response.status_code == 409
    assert response.json() == {"detail": "billing result needs manual review"}


def test_char_swap_config_stays_on_studio_free_path(tmp_path, monkeypatch) -> None:
    import char_swap_config as cfg

    monkeypatch.setattr(cfg, "CONFIG_PATH", tmp_path / "char_swap_config.json")
    path = tmp_path / "char_swap_config.json"
    path.write_text('{"force_free": false}\n', encoding="utf-8")

    loaded = cfg.load_config()
    assert loaded["force_free"] is True
    saved = cfg.save_config({"force_free": False})
    assert saved["force_free"] is True
    assert cfg.DEFAULTS["force_free"] is True

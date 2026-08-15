from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import post_pipeline


ROOT = Path(__file__).resolve().parents[1]


class PostPipelineConcurrencyTests(unittest.TestCase):
    def test_same_image_stays_active_until_all_overlapping_callers_finish(self) -> None:
        first_entered = threading.Event()
        release_first = threading.Event()
        second_entered = threading.Event()
        release_second = threading.Event()
        calls = 0
        calls_lock = threading.Lock()

        def fake_process(stem, *, overrides=None, only_missing=False):
            nonlocal calls
            with calls_lock:
                calls += 1
                call_number = calls
            if call_number == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(timeout=2))
            else:
                second_entered.set()
                self.assertTrue(release_second.wait(timeout=2))
            return {"ok": True, "image_id": stem}

        image_id = "20260727_011503_501"
        stem = post_pipeline._stem_from_image_id(image_id)
        with patch.object(post_pipeline, "_process_image_locked", side_effect=fake_process):
            first = threading.Thread(target=post_pipeline.process_image, args=(image_id,))
            second = threading.Thread(target=post_pipeline.process_image, args=(image_id,))
            first.start()
            self.assertTrue(first_entered.wait(timeout=1))
            second.start()
            self.assertIn(stem, post_pipeline.active_pipeline_ids())

            release_first.set()
            self.assertTrue(second_entered.wait(timeout=1))
            self.assertIn(stem, post_pipeline.active_pipeline_ids())

            release_second.set()
            first.join(timeout=1)
            second.join(timeout=1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertNotIn(stem, post_pipeline.active_pipeline_ids())

    def test_start_pipeline_returns_running_job_without_reentering_status_lock(self) -> None:
        script = """
import json
import post_pipeline

with post_pipeline._LOCK:
    post_pipeline._JOB.clear()
    post_pipeline._JOB.update({
        "status": "running",
        "message": "existing job",
        "total": 2,
        "done": 1,
        "ok": 1,
        "fail": 0,
        "items": [],
    })

result = post_pipeline.start_pipeline({"image_id": "deadlock-probe"})
print(json.dumps(result, ensure_ascii=False))
"""
        try:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(f"start_pipeline deadlocked while reporting an existing job: {exc}")

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertFalse(result["ok"])
        self.assertEqual("running", result["job"]["status"])
        self.assertEqual(1, result["job"]["done"])


class PostPipelineBacklogPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_backlog_cache = dict(post_pipeline._BACKLOG_CACHE)
        post_pipeline._BACKLOG_CACHE.clear()
        post_pipeline._BACKLOG_CACHE.update(
            {
                "sig": None,
                "result": None,
                "cached_at": 0.0,
                "dirty": True,
                "generation": 0,
            }
        )

    def tearDown(self) -> None:
        post_pipeline._BACKLOG_CACHE.clear()
        post_pipeline._BACKLOG_CACHE.update(self.old_backlog_cache)

    def test_backlog_builds_one_artifact_index_without_per_item_glob(self) -> None:
        stem = "20260727_120000_501"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp)
            for suffix in (
                ".png",
                "_up2x.png",
                "_up2x_clean.png",
                "_final.png",
            ):
                (generated_dir / f"{stem}{suffix}").write_bytes(b"image")
            (generated_dir / f"{stem}.png.meta.json").write_text(
                json.dumps(
                    {
                        "pipeline_steps": [
                            "upscale:2x",
                            "metadata:clean",
                        ]
                    }
                ),
                encoding="utf-8",
            )
            cfg = {
                "upscale": {"enabled": True},
                "mosaic": {"enabled": False},
                "metadata": {"enabled": True},
                "only_missing": True,
                "anr_root": "",
            }
            with (
                patch.object(post_pipeline, "GENERATED_DIR", generated_dir),
                patch(
                    "generated_gallery.scan_all_items",
                    return_value=[{"id": stem}],
                ),
                patch.object(
                    post_pipeline,
                    "merge_pipeline_config",
                    return_value=cfg,
                ),
                patch.object(
                    Path,
                    "glob",
                    side_effect=AssertionError(
                        "backlog must not glob once per image"
                    ),
                ),
            ):
                missing = post_pipeline.list_items_needing_pipeline()

        self.assertEqual(missing, [])

    def test_concurrent_backlog_requests_share_one_refresh(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        calls = 0
        calls_lock = threading.Lock()
        results: list[dict] = []

        def slow_scan(*, overrides=None):
            nonlocal calls
            with calls_lock:
                calls += 1
            entered.set()
            self.assertTrue(release.wait(timeout=2))
            return ["one"]

        def request_backlog() -> None:
            results.append(post_pipeline.count_items_needing_pipeline())

        with (
            patch.object(
                post_pipeline,
                "_backlog_cache_signature",
                return_value=("stable",),
            ),
            patch.object(
                post_pipeline,
                "list_items_needing_pipeline",
                side_effect=slow_scan,
            ),
        ):
            first = threading.Thread(target=request_backlog)
            second = threading.Thread(target=request_backlog)
            first.start()
            self.assertTrue(entered.wait(timeout=1))
            second.start()
            release.set()
            first.join(timeout=2)
            second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(calls, 1)
        self.assertEqual([result["count"] for result in results], [1, 1])

    def test_invalidation_keeps_last_backlog_receipt_for_fast_readers(self) -> None:
        post_pipeline._BACKLOG_CACHE.update(
            {
                "sig": ("old",),
                "result": {"count": 7, "sample": ["one"]},
                "cached_at": 123.0,
                "dirty": False,
            }
        )

        post_pipeline.invalidate_backlog_cache()

        self.assertEqual(
            post_pipeline._BACKLOG_CACHE["result"],
            {"count": 7, "sample": ["one"]},
        )
        self.assertTrue(post_pipeline._BACKLOG_CACHE["dirty"])


class PostPipelineAnrOptionalTests(unittest.TestCase):
    def test_missing_anr_still_upscales_and_declares_lanczos(self) -> None:
        from PIL import Image

        stem = "unit_no_anr_upscale"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp)
            source = generated_dir / f"{stem}.png"
            Image.new("RGB", (8, 8), (12, 34, 56)).save(source)
            cfg = {
                "upscale": {"enabled": True, "scale": 2},
                "mosaic": {"enabled": True, "method": "像素"},
                "metadata": {"enabled": True},
                "anr_root": "",
            }
            with (
                patch.object(post_pipeline, "GENERATED_DIR", generated_dir),
                patch.object(post_pipeline, "merge_pipeline_config", return_value=cfg),
                patch.object(
                    post_pipeline,
                    "mosaic_runtime_status",
                    return_value={"ok": False, "message": "未找到 ANR 打码插件"},
                ),
            ):
                result = post_pipeline._process_image_locked(stem)
                state = post_pipeline.pipeline_item_state(stem, overrides=cfg)

            self.assertTrue(result["ok"])
            self.assertEqual(result["upscale_engine"], "lanczos")
            self.assertIn("upscale:2x", result["steps"])
            self.assertIn("mosaic:unavailable", result["steps"])
            self.assertIn("metadata:clean", result["steps"])
            upscaled = generated_dir / f"{stem}_up2x.png"
            final = generated_dir / f"{stem}_final.png"
            self.assertTrue(upscaled.exists())
            self.assertTrue(final.exists())
            with Image.open(upscaled) as img:
                self.assertEqual(img.size, (16, 16))
            self.assertTrue(state["upscale"])
            self.assertTrue(state["mosaic"])
            self.assertNotIn("mosaic", state["missing"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from butler.workflow import ButlerWorkflowRuntime


class ButlerCanaryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_one_canary_stops_at_submission_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ButlerWorkflowRuntime(Path(tmp) / "state.db")
            self.addAsyncCleanup(runtime.close)
            runtime.store.create_task(
                "wf-canary",
                thread_id="wf-canary",
                kind="butler_workflow",
                title="one image canary",
                input_data={"message": "canary"},
            )
            args = {
                "work_ids": [145765334],
                "copies_per_work": 1,
                "generation": {"steps": 28},
                "remix_recipe": {
                    "transform": {
                        "enabled": True,
                        "preset_id": "oc_12gg_f",
                        "mode": "replace_female",
                    },
                    "style": {
                        "mode": "preset",
                        "preset_id": "granblue",
                        "preset_label": "碧蓝幻想画风",
                        "replace": "granblue_fantasy_(style)",
                    },
                    "sanitize": {"enabled": True},
                },
                "extra": "canary",
            }
            status = {
                "status": "done",
                "done": 1,
                "total": 1,
                "ok_count": 1,
                "fail_count": 0,
                "items": [
                    {
                        "ok": True,
                        "gallery_id": "site",
                        "work_id": 145765334,
                        "page_index": 0,
                        "filename": "canary-one.png",
                        "transform_applied": True,
                        "style_applied": True,
                        "style_replacements": 2,
                        "summary": "替换后的角色",
                        "remix": {"preset_id": "oc_12gg_f", "mode": "replace_female"},
                    }
                ],
            }
            prepared_payload = {
                "prepared": {
                    "package_id": "wf-canary",
                    "total_images": 1,
                    "upload_started": False,
                    "items": [{"group_id": "145765334", "image_ids": ["canary-one"]}],
                }
            }
            start = Mock(
                return_value={
                    "ok": True,
                    "batch": {"id": "generation-canary", "status": "running"},
                }
            )
            prepare = Mock(return_value=prepared_payload)

            with patch("butler.workflow.legacy._require_work", return_value={}), patch(
                "butler.workflow.legacy._batch_targets",
                return_value=[{"work_id": 145765334, "page_index": 0}],
            ), patch("nai_batch.start_batch", start), patch(
                "nai_batch.batch_status", return_value=status
            ), patch("nai_batch.cancel_batch"), patch(
                "pixiv_launch.prepare_submission_package", prepare
            ), patch("pixiv_launch.upload_illust") as upload:
                result = await runtime._execute_batch(
                    "wf-canary",
                    args,
                    "operation-canary",
                    prepare_pixiv=True,
                )
            await runtime.close()

            self.assertEqual(result["generated"], 1)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["quality"]["replacement_applied"], 1)
            self.assertEqual(result["quality"]["style_applied"], 1)
            self.assertEqual(result["quality"]["style_preset_label"], "碧蓝幻想画风")
            self.assertTrue(result["items"][0]["transform_applied"])
            self.assertTrue(result["items"][0]["style_applied"])
            self.assertEqual(result["items"][0]["page_index"], 0)
            self.assertEqual(result["prepared"]["total_images"], 1)
            self.assertFalse(result["prepared"]["upload_started"])
            start.assert_called_once()
            # 8797 与工作台一致：出图固定走 Opus 免费档（force_free=true）
            self.assertTrue(start.call_args.kwargs["force_free"])
            self.assertTrue(start.call_args.kwargs["generate"])
            self.assertFalse(start.call_args.kwargs["preview_only"])
            prepare.assert_called_once_with(
                {
                    "series": [
                        {"group_id": "145765334", "image_ids": ["canary-one"]}
                    ],
                    "extra": "canary",
                    "package_id": "wf-canary",
                }
            )
            upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()

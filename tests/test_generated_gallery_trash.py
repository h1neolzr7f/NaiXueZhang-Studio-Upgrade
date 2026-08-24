from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generated_gallery as gallery


class GeneratedGalleryTrashTests(unittest.TestCase):
    def test_source_info_prefers_local_path_with_extension(self) -> None:
        gallery.invalidate_source_cache()
        try:
            result = gallery.get_cached_source_info(
                501,
                lambda _work_id: {
                    "work": {"title": "source"},
                    "images": [
                        {
                            "file_name": "501_p0",
                            "local_path": "images/NAI/100909/501_p0.webp",
                        }
                    ],
                },
            )
        finally:
            gallery.invalidate_source_cache()

        self.assertEqual(result["thumb"], "/data/images/NAI/100909/501_p0.webp")

    def test_cold_group_cache_uses_directory_version_without_png_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_dir = root / "generated"
            cache_file = root / "cache" / "groups.json"
            generated_dir.mkdir()
            cache_file.parent.mkdir()
            (generated_dir / "20260727_011500_501.png").write_bytes(b"image")
            signature = [1, 1.0, generated_dir.stat().st_mtime_ns]
            cache_file.write_text(
                json.dumps(
                    {
                        "sig": signature,
                        "groups": [{"group_id": "501", "count": 1}],
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch.object(
                gallery, "_GROUPS_CACHE_FILE", cache_file
            ), patch.object(
                gallery, "_scan_signature", side_effect=AssertionError("full scan")
            ):
                gallery.invalidate_scan_cache()
                groups = gallery.list_groups()

        self.assertEqual(groups, [{"group_id": "501", "count": 1}])

    def test_external_same_count_replacement_invalidates_in_memory_scan(self) -> None:
        first_id = "20260727_011510_501"
        replacement_id = "20260727_011511_501"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            first = generated_dir / f"{first_id}.png"
            first.write_bytes(b"first")
            fixed_time = first.stat().st_mtime

            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch.object(
                gallery, "_ITEMS_CACHE_FILE", generated_dir / ".items_cache.json"
            ), patch.object(
                gallery, "_GROUPS_CACHE_FILE", generated_dir / ".groups_cache.json"
            ):
                gallery.invalidate_scan_cache()
                initial = gallery.scan_all_items(force=True)
                old_dir_time = generated_dir.stat().st_mtime

                first.unlink()
                replacement = generated_dir / f"{replacement_id}.png"
                replacement.write_bytes(b"replacement")
                os.utime(replacement, (fixed_time, fixed_time))
                os.utime(generated_dir, (old_dir_time + 2, old_dir_time + 2))

                refreshed = gallery.scan_all_items()

        self.assertEqual([item["id"] for item in initial], [first_id])
        self.assertEqual([item["id"] for item in refreshed], [replacement_id])
    def test_deleted_item_can_be_restored_with_all_sidecars(self) -> None:
        image_id = "20260719_101500_501"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            expected = {
                f"{image_id}.png": b"primary",
                f"{image_id}.png.meta.json": json.dumps({"work_id": 501}).encode(),
                f"{image_id}.thumb.webp": b"thumb",
                f"{image_id}_up2x.png": b"derived",
                f"{image_id}_up2x.png.meta.json": b"{}",
            }
            for name, content in expected.items():
                (generated_dir / name).write_bytes(content)

            with patch.object(gallery, "GENERATED_DIR", generated_dir):
                deleted = gallery.delete_item(image_id)
                self.assertFalse((generated_dir / f"{image_id}.png").exists())
                trash_entries = gallery.list_deleted()
                restored = gallery.restore_deleted(deleted["trash_id"])

            self.assertTrue(deleted["undo_available"])
            self.assertEqual(trash_entries[0]["trash_id"], deleted["trash_id"])
            self.assertEqual(trash_entries[0]["file_count"], len(expected))
            self.assertEqual(restored["restored_files"], len(expected))
            for name, content in expected.items():
                self.assertEqual((generated_dir / name).read_bytes(), content)

    def test_deleted_group_is_one_restore_action(self) -> None:
        image_ids = ["20260719_101501_501", "20260719_101502_501"]
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            for image_id in image_ids:
                (generated_dir / f"{image_id}.png").write_bytes(image_id.encode())
            group = {"items": [{"id": image_id} for image_id in image_ids]}

            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch.object(
                gallery, "get_group", return_value=group
            ):
                deleted = gallery.delete_group("site:501")
                entries = [path for path in (generated_dir / ".trash").iterdir() if path.is_dir()]
                restored = gallery.restore_deleted(deleted["trash_id"])

            self.assertEqual(len(entries), 1)
            self.assertEqual(deleted["deleted"], 2)
            self.assertEqual(restored["restored_files"], 2)
            self.assertTrue(all((generated_dir / f"{image_id}.png").is_file() for image_id in image_ids))

    def test_restore_accepts_identical_file_recreated_by_post_pipeline(self) -> None:
        image_id = "20260727_011500_501"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            primary = generated_dir / f"{image_id}.png"
            primary.write_bytes(b"same-primary")

            with patch.object(gallery, "GENERATED_DIR", generated_dir):
                deleted = gallery.delete_item(image_id)
                # Simulate a post-processing worker finishing after deletion.
                primary.write_bytes(b"same-primary")
                restored = gallery.restore_deleted(deleted["trash_id"])

            self.assertTrue(restored["ok"])
            self.assertEqual(primary.read_bytes(), b"same-primary")
            self.assertEqual(restored["already_present_files"], 1)

    def test_same_source_work_merges_generation_series(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            first = "20260727_011501_501.png"
            second = "20260727_011502_501.png"
            (generated_dir / first).write_bytes(b"first")
            (generated_dir / second).write_bytes(b"second")

            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch.object(
                gallery,
                "ensure_thumbnail",
                return_value=True,
            ):
                gallery.invalidate_scan_cache()
                gallery.register_generated(
                    first,
                    work_id=501,
                    generation_series_id="task-a",
                )
                gallery.register_generated(
                    second,
                    work_id=501,
                    generation_series_id="task-b",
                )
                groups = gallery.list_groups(force=True)
                deleted = gallery.delete_group("501")

            self.assertEqual({group["group_id"] for group in groups}, {"501"})
            self.assertEqual(deleted["deleted"], 2)
            self.assertFalse((generated_dir / first).exists())
            self.assertFalse((generated_dir / second).exists())

    def test_standalone_images_stay_split_by_generation_series(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            first = "20260727_011601.png"
            second = "20260727_011602.png"
            (generated_dir / first).write_bytes(b"first")
            (generated_dir / second).write_bytes(b"second")

            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch.object(
                gallery,
                "ensure_thumbnail",
                return_value=True,
            ):
                gallery.invalidate_scan_cache()
                gallery.register_generated(first, generation_series_id="task-a")
                gallery.register_generated(second, generation_series_id="task-b")
                groups = gallery.list_groups(force=True)

            self.assertEqual(
                {group["group_id"] for group in groups},
                {"run:task-a:standalone", "run:task-b:standalone"},
            )

    def test_delete_waits_until_post_pipeline_releases_image(self) -> None:
        image_id = "20260727_011503_501"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            (generated_dir / f"{image_id}.png").write_bytes(b"primary")
            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch(
                "post_pipeline.active_pipeline_ids",
                return_value={image_id},
            ):
                with self.assertRaises(gallery.GeneratedArtifactBusy):
                    gallery.delete_item(image_id)

            self.assertTrue((generated_dir / f"{image_id}.png").exists())

    def test_assigning_series_to_legacy_image_preserves_pipeline_metadata(self) -> None:
        image_id = "20260727_011504_501"
        with tempfile.TemporaryDirectory() as temp:
            generated_dir = Path(temp) / "generated"
            generated_dir.mkdir()
            png = generated_dir / f"{image_id}.png"
            png.write_bytes(b"primary")
            meta_path = generated_dir / f"{image_id}.png.meta.json"
            meta_path.write_text(
                json.dumps(
                    {
                        "work_id": 501,
                        "created_at": "2026-07-27T01:15:04",
                        "pipeline_steps": ["metadata:clean"],
                        "processed_filename": f"{image_id}_final.png",
                        "prompt_snapshot": {"char_captions": [{"caption": "ding_(oc)"}]},
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(gallery, "GENERATED_DIR", generated_dir), patch.object(
                gallery,
                "ensure_thumbnail",
                return_value=True,
            ):
                gallery.register_generated(
                    png.name,
                    work_id=501,
                    generation_series_id="legacy-ding",
                )
            updated = json.loads(meta_path.read_text(encoding="utf-8"))

        self.assertEqual(updated["generation_series_id"], "legacy-ding")
        self.assertEqual(updated["created_at"], "2026-07-27T01:15:04")
        self.assertEqual(updated["pipeline_steps"], ["metadata:clean"])
        self.assertEqual(updated["prompt_snapshot"]["char_captions"][0]["caption"], "ding_(oc)")


if __name__ == "__main__":
    unittest.main()

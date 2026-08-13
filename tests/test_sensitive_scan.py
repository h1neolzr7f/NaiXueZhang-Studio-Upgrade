from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from paths import relative_to_canonical
from scripts.scan_sensitive import DEFAULT_PATTERNS, git_candidate_paths, scan


class SensitiveScanTests(unittest.TestCase):
    def test_source_field_names_and_short_test_tokens_are_not_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "fixture.py").write_text(
                '{"refresh_token": "", "token": "pst-test-value", '
                '"api_key": "sk-secret-value"}',
                encoding="utf-8",
            )
            self.assertEqual(scan(root, DEFAULT_PATTERNS), [])

    def test_high_entropy_literal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = "pst-" + "A" * 64
            (root / "leak.json").write_text(
                '{"token":"' + secret + '"}',
                encoding="utf-8",
            )
            hits = scan(root, DEFAULT_PATTERNS)
            self.assertEqual(len(hits), 1)
            self.assertIn("type=novelai-token", hits[0])
            self.assertIn("fingerprint=sha256:", hits[0])
            self.assertNotIn(secret, hits[0])

    def test_github_tokens_are_detected_without_echoing_the_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = "github_pat_" + "A1_" * 16
            (root / "credentials.txt").write_text(secret, encoding="utf-8")

            hits = scan(root)

            self.assertEqual(len(hits), 1)
            self.assertIn("type=github-fine-grained-token", hits[0])
            self.assertNotIn(secret, hits[0])

    def test_private_runtime_tree_is_aggregated_and_never_opened(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "data" / "images"
            private.mkdir(parents=True)
            (private / "account-name.png").write_bytes(b"private image")
            (private / "second.webp").write_bytes(b"private image 2")

            hits = scan(root)

            self.assertEqual(len(hits), 1)
            self.assertIn("data/images/ | type=private-runtime-data | files=2", hits[0])
            self.assertNotIn("account-name", hits[0])

    def test_public_seed_is_allowed_but_its_content_is_still_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = root / "data"
            data.mkdir()
            (data / "tag_dict.json").write_text('{"safe": true}', encoding="utf-8")
            self.assertEqual(scan(root), [])

            secret = "ghp_" + "A" * 36
            (data / "tag_dict.json").write_text(secret, encoding="utf-8")
            hits = scan(root)
            self.assertEqual(len(hits), 1)
            self.assertIn("type=github-classic-token", hits[0])
            self.assertNotIn(secret, hits[0])

    def test_backup_sources_and_local_config_are_rejected_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "config.json").write_text("{}", encoding="utf-8")
            backup = root / "web.backup-20260811"
            backup.mkdir()
            (backup / "app.js").write_text("// old", encoding="utf-8")
            (root / "crawler.py.bak-20260811").write_text("# old", encoding="utf-8")
            (root / "progress.md").write_text("local agent notes", encoding="utf-8")

            hits = scan(root)

            self.assertEqual(len(hits), 4)
            self.assertTrue(any("config.json | type=local-configuration" in hit for hit in hits))
            self.assertTrue(any("web.backup-20260811/ | type=backup-source" in hit for hit in hits))
            self.assertTrue(any("crawler.py.bak-20260811 | type=backup-source" in hit for hit in hits))
            self.assertTrue(any("progress.md | type=local-work-state" in hit for hit in hits))

    def test_absolute_user_path_reports_only_a_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            local_path = "C:\\Users\\private-user\\Documents\\gallery"
            (root / "settings.txt").write_text(local_path, encoding="utf-8")

            hits = scan(root)

            self.assertEqual(len(hits), 1)
            self.assertIn("type=absolute-user-path", hits[0])
            self.assertNotIn("private-user", hits[0])

    def test_pixiv_user_urls_and_lowercase_tag_text_are_not_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "source.py").write_text(
                'url = "https://www.pixiv.net/users/123456"\n'
                'tag = "aizawashiro_long_public_tag_text_123456789"\n',
                encoding="utf-8",
            )

            self.assertEqual(scan(root), [])

    def test_git_candidates_exclude_ignored_private_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text("data/*\n", encoding="utf-8")
            (root / "source.py").write_text("print('safe')\n", encoding="utf-8")
            private = root / "data"
            private.mkdir()
            (private / "ai.local.json").write_text(
                '{"api_key":"' + "A" * 48 + '"}', encoding="utf-8"
            )

            candidates = git_candidate_paths(root)
            relative = {relative_to_canonical(path, root) for path in candidates}

            self.assertIn("source.py", relative)
            self.assertNotIn("data/ai.local.json", relative)
            self.assertEqual(scan(root, candidate_paths=candidates), [])


if __name__ == "__main__":
    unittest.main()

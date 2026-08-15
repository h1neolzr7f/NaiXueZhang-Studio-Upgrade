from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_bench():
    path = Path(__file__).resolve().parents[1] / "scripts" / "bench_gallery.py"
    spec = importlib.util.spec_from_file_location("bench_gallery", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class BenchGalleryTests(unittest.TestCase):
    def test_synthetic_query_is_repeatable_and_filters(self) -> None:
        bench = _load_bench()
        result = bench.run_bench(count=200, repeats=3, query="arknights amiya")
        self.assertEqual(result["count"], 200)
        self.assertGreater(result["hits"], 0)
        self.assertLess(result["hits"], 200)
        self.assertGreaterEqual(result["p95_ms"], 0)
        self.assertIn("synthetic_in_memory", result["dataset"])

#!/usr/bin/env python3
"""Cloud-safe gallery query micro-bench.

This does not claim 10k/100k Windows numbers. It times query parsing and an
in-memory filter over a synthetic set so Phase 0 has a repeatable command.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _synthetic_rows(count: int) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        rows.append(
            {
                "work_id": index,
                "prompt": f"1girl arknights amiya look{index % 17}",
                "model": "nai-diffusion-4-5-full" if index % 2 == 0 else "nai-diffusion-4-full",
                "width": 832,
                "height": 1216,
            }
        )
    return rows


def _filter(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    from search import parse_query

    groups = parse_query(query)
    tokens = [term.value.lower() for group in groups for term in group.terms if not term.exclude]
    if not tokens:
        return rows
    hits = []
    for row in rows:
        haystack = f"{row['prompt']} {row['model']}".lower()
        if all(token in haystack for token in tokens):
            hits.append(row)
    return hits


def run_bench(*, count: int, repeats: int, query: str) -> dict[str, Any]:
    rows = _synthetic_rows(count)
    timings_ms: list[float] = []
    hit_count = 0
    for _ in range(repeats):
        started = time.perf_counter()
        hits = _filter(rows, query)
        timings_ms.append((time.perf_counter() - started) * 1000.0)
        hit_count = len(hits)
    timings_ms.sort()
    p95_index = max(0, int(len(timings_ms) * 0.95) - 1)
    return {
        "script": "scripts/bench_gallery.py",
        "dataset": "synthetic_in_memory",
        "count": count,
        "repeats": repeats,
        "query": query,
        "hits": hit_count,
        "p50_ms": round(statistics.median(timings_ms), 3),
        "p95_ms": round(timings_ms[p95_index], 3),
        "max_ms": round(timings_ms[-1], 3),
        "notes": "Not a Windows 10k/100k claim. See PENDING_LOCAL_WINDOWS WIN-010.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud-safe gallery query micro-bench")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--query", default="arknights amiya")
    args = parser.parse_args()
    result = run_bench(count=args.count, repeats=args.repeats, query=args.query)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

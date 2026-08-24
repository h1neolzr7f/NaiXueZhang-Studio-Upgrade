"""随机刷新（shuffle）排序的回归测试。

契约：
- 同一 seed 下顺序稳定（翻页/无限滚动不重复、不遗漏）
- 不同 seed 给出不同顺序（换一批）
- random 排序仍覆盖全部匹配行（只是顺序不同）
"""

from __future__ import annotations

import json
from pathlib import Path

from db import Database


def _seed_db(tmp_path: Path, count: int = 30) -> Database:
    db = Database(tmp_path / "shuffle.db")
    for work_id in range(1, count + 1):
        item = {"id": work_id, "title": str(work_id), "AI_type": "NAI"}
        db.conn.execute(
            """
            INSERT INTO works(id, title, ai_type, create_date, list_json)
            VALUES (?, ?, 'NAI', ?, ?)
            """,
            (work_id, str(work_id), "2024-01-01T00:00:00+00:00", json.dumps(item)),
        )
    db.conn.commit()
    return db


def test_random_sort_is_stable_for_same_seed_across_pages(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        page1 = db.search_works(sort="random", seed=42, page=1, page_size=10)
        page2 = db.search_works(sort="random", seed=42, page=2, page_size=10)
        page3 = db.search_works(sort="random", seed=42, page=3, page_size=10)
        again1 = db.search_works(sort="random", seed=42, page=1, page_size=10)
    finally:
        db.close()

    ids1 = [item["id"] for item in page1["items"]]
    ids2 = [item["id"] for item in page2["items"]]
    ids3 = [item["id"] for item in page3["items"]]

    # 同 seed 重查第一页，顺序完全一致
    assert ids1 == [item["id"] for item in again1["items"]]
    # 三页合起来恰好覆盖全部 30 行，无重复无遗漏
    assert sorted(ids1 + ids2 + ids3) == list(range(1, 31))


def test_random_sort_changes_order_with_different_seed(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        orders = {
            tuple(
                item["id"]
                for item in db.search_works(
                    sort="random", seed=seed, page=1, page_size=30
                )["items"]
            )
            for seed in (1, 7, 123456)
        }
    finally:
        db.close()

    # 三个不同 seed 至少产生两种不同顺序（理论上可能撞序，30! 空间下概率可忽略）
    assert len(orders) >= 2


def test_bookmarks_and_views_sort_use_engagement_columns(tmp_path: Path) -> None:
    db = Database(tmp_path / "engagement.db")
    rows = [(1, 1, 100), (2, 50, 10), (3, 10, 200)]
    try:
        for work_id, bookmarks, views in rows:
            db.conn.execute(
                """
                INSERT INTO works(id, title, ai_type, create_date, list_json, total_bookmarks, total_view)
                VALUES (?, ?, 'NAI', ?, ?, ?, ?)
                """,
                (
                    work_id,
                    str(work_id),
                    "2024-01-01T00:00:00+00:00",
                    json.dumps({"id": work_id}),
                    bookmarks,
                    views,
                ),
            )
        db.conn.commit()
        by_bookmarks = [
            item["id"]
            for item in db.search_works(sort="bookmarks", page=1, page_size=10)["items"]
        ]
        by_views = [
            item["id"]
            for item in db.search_works(sort="views", page=1, page_size=10)["items"]
        ]
    finally:
        db.close()

    assert by_bookmarks == [2, 3, 1]
    assert by_views == [3, 1, 2]


def test_random_sort_default_seed_zero_is_deterministic(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    try:
        first = db.search_works(sort="random", page=1, page_size=30)
        second = db.search_works(sort="random", page=1, page_size=30)
    finally:
        db.close()

    assert [i["id"] for i in first["items"]] == [i["id"] for i in second["items"]]

"""Shared empty-gallery gate for crawler start (HTTP, Butler, watchdog)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

EMPTY_GALLERY_CRAWL_MSG = (
    "主图库为空时不要启动或配置采集。请先打开图库页用 AITag 发现参考（发现结果不会写入主库）。"
)


def main_gallery_empty(db: Any | None = None) -> bool:
    """True when the main gallery has no works, or the count cannot be read.

    Fail closed: a locked/missing database is treated as empty so crawlers
    cannot start while the guard is blind.
    """

    owned = None
    try:
        if db is None:
            from db import Database
            from paths import data_dir

            owned = Database(Path(data_dir()) / "aitag.db")
            db = owned
        return int(db.count_works() or 0) <= 0
    except Exception:
        return True
    finally:
        if owned is not None:
            try:
                owned.close()
            except Exception:
                pass


def require_gallery_for_crawler() -> None:
    if main_gallery_empty():
        raise ValueError(EMPTY_GALLERY_CRAWL_MSG)

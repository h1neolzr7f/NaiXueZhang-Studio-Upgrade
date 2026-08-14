from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from db_compression import decompress_if_needed
from search import build_prompt_fts_query, build_works_fts_query
from nai_tag_index import build_nai_facet_filter


ARK_MATCH_SQL = """
    LOWER(COALESCE(works.title, '') || COALESCE(works.caption, '') || COALESCE(works.tags, '')) LIKE '%明日方舟%'
    OR LOWER(COALESCE(works.title, '') || COALESCE(works.caption, '') || COALESCE(works.tags, '')) LIKE '%arknights%'
    OR LOWER(COALESCE(works.title, '') || COALESCE(works.caption, '') || COALESCE(works.tags, '')) LIKE '%アークナイツ%'
"""


_PRIVATE_WORK_PATH_KEYS = frozenset(
    {
        "source_path",
        "database_path",
        "db_path",
        "images_dir",
        "absolute_path",
    }
)


def local_dataset_clause(self, scope: str) -> tuple[str, list[Any]]:
    scope = (scope or "local").strip().lower()
    if scope in {"all", "none", ""}:
        return "", []
    if scope in {"local", "local_nai", "indexed"}:
        return (
            """
            UPPER(COALESCE(works.ai_type, '')) = 'NAI'
            AND works.list_json IS NOT NULL
            """,
            [],
        )
    if scope in {"arknights_nai", "arknights", "arknights-nai"}:
        return (
            f"""
            (
                {ARK_MATCH_SQL.strip()}
            )
            AND UPPER(COALESCE(works.ai_type, '')) = 'NAI'
            AND works.list_json IS NOT NULL
            """,
            [],
        )
    works_match, works_excludes = build_works_fts_query(scope)
    parts: list[str] = []
    params: list[Any] = []
    if works_match:
        parts.append(
            "works.id IN (SELECT work_id FROM works_fts WHERE works_fts MATCH ?)"
        )
        params.append(works_match)
    for term in works_excludes:
        parts.append(
            """
            LOWER(
                COALESCE(works.title, '') || ' ' ||
                COALESCE(works.caption, '') || ' ' ||
                COALESCE(works.tags, '') || ' ' ||
                COALESCE(works.ai_type, '')
            ) NOT LIKE ?
            """
        )
        params.append(f"%{term.lower()}%")
    return " AND ".join(parts), params


def _strip_private_work_paths(value: Any) -> Any:
    """Return a detached public payload without local filesystem locations."""

    if isinstance(value, dict):
        return {
            key: _strip_private_work_paths(item)
            for key, item in value.items()
            if str(key) not in _PRIVATE_WORK_PATH_KEYS
        }
    if isinstance(value, list):
        return [_strip_private_work_paths(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_private_work_paths(item) for item in value)
    return value


def _attach_page_status(detail: dict[str, Any]) -> dict[str, Any]:
    """Surface partial-page intake state so the frontend can badge it."""

    work = detail.get("work")
    if not isinstance(work, dict):
        return detail
    images = detail.get("images")
    accepted = len(images) if isinstance(images, list) else 0
    total_raw = work.get("source_page_count")
    try:
        total = int(total_raw) if total_raw is not None else None
    except (TypeError, ValueError):
        total = None
    partial = bool(total is not None and accepted < total)
    work["partial"] = partial
    detail["page_status"] = {
        "accepted": accepted,
        "total": total,
        "partial": partial,
    }
    return detail


def _mark_partial_list_item(work: dict[str, Any]) -> None:
    total_raw = work.get("source_page_count")
    if total_raw is None:
        return
    try:
        work["partial"] = int(work.get("image_count") or 0) < int(total_raw)
    except (TypeError, ValueError):
        return


def work_in_scope(self, work_id: int, scope: str) -> bool:
    clause, params = self._local_dataset_clause(scope)
    if not clause:
        return True

    def action() -> bool:
        row = self.conn.execute(
            f"SELECT 1 FROM works WHERE works.id = ? AND {clause}",
            [work_id, *params],
        ).fetchone()
        return row is not None

    return self._run(action)

def get_work_detail(self, work_id: int) -> dict[str, Any] | None:
    def action():
        row = self.conn.execute(
            """
            SELECT detail_json, list_json, image_count, total_view, total_bookmarks
            FROM works WHERE id = ?
            """,
            (work_id,),
        ).fetchone()
        if not row:
            return None
        if row["detail_json"]:
            detail = json.loads(decompress_if_needed(row["detail_json"]))
            work = detail.get("work") or {}
            if isinstance(work, dict):
                detail["work"] = self._hydrate_work_item(work, row)
            images = detail.get("images") or []
            if isinstance(images, list):
                cache_rows = {
                    int(cache_row["page_index"] or 0): cache_row
                    for cache_row in self.conn.execute(
                        """
                        SELECT page_index, local_path, downloaded
                        FROM work_images
                        WHERE work_id = ?
                        """,
                        (work_id,),
                    ).fetchall()
                }
                for fallback_index, image in enumerate(images):
                    if not isinstance(image, dict):
                        continue
                    raw_index = image.get("page_index")
                    if raw_index is None:
                        match = re.search(r"_p(\d+)(?:\.[^.]+)?$", str(image.get("file_name") or ""))
                        page_index = int(match.group(1)) if match else fallback_index
                    else:
                        page_index = int(raw_index)
                    cache_row = cache_rows.get(page_index)
                    image["page_index"] = page_index
                    image["local_path"] = (
                        cache_row["local_path"]
                        if cache_row
                        and int(cache_row["downloaded"] or 0) == 1
                        and cache_row["local_path"]
                        else None
                    )
            return _attach_page_status(detail)
        if row["list_json"]:
            work = self._hydrate_work_item(json.loads(row["list_json"]), row)
            return _attach_page_status({"work": work, "images": []})
        return None

    return self._run(action)

def get_work_prompt_snippet(
    self, work_id: int, page_index: int = 0, *, max_len: int = 640
) -> dict[str, Any]:
    """Lightweight prompt read for sidebar preview (no extract_chars)."""

    def action() -> dict[str, Any]:
        limit = max(120, min(int(max_len), 2000))
        row = self.conn.execute(
            """
            SELECT prompt_text, ai_json, page_index
            FROM work_images
            WHERE work_id = ? AND page_index = ?
            LIMIT 1
            """,
            (work_id, page_index),
        ).fetchone()
        if not row:
            row = self.conn.execute(
                """
                SELECT prompt_text, ai_json, page_index
                FROM work_images
                WHERE work_id = ?
                ORDER BY page_index
                LIMIT 1
                """,
                (work_id,),
            ).fetchone()
        if row:
            raw = (row["prompt_text"] or decompress_if_needed(row["ai_json"]) or "").strip()
            if raw:
                snippet = raw if len(raw) <= limit else raw[: limit - 1] + "…"
                return {
                    "snippet": snippet,
                    "page_index": int(row["page_index"] or 0),
                    "source": "work_images",
                }
        return {"snippet": "", "page_index": page_index, "source": "none"}

    return self._run(action)

def get_work_lite(self, work_id: int) -> dict[str, Any] | None:
    """Hover-preview friendly payload: titles + image paths only."""

    def action() -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT list_json, image_count, total_view, total_bookmarks
            FROM works WHERE id = ?
            """,
            (work_id,),
        ).fetchone()
        if not row:
            return None
        work: dict[str, Any] = {"id": work_id}
        if row["list_json"]:
            try:
                loaded = json.loads(row["list_json"])
                if isinstance(loaded, dict):
                    work.update(loaded)
            except Exception:
                pass
        work = self._hydrate_work_item(work, row)
        image_rows = self.conn.execute(
            """
            SELECT file_name, page_index, local_path, image_type, author_id
            FROM work_images
            WHERE work_id = ?
            ORDER BY page_index
            """,
            (work_id,),
        ).fetchall()
        images = [
            {
                "file_name": r["file_name"],
                "page_index": int(r["page_index"] or 0),
                "local_path": r["local_path"],
                # Older rows can lack per-image routing metadata.  The work
                # payload is authoritative for those values and lets the
                # frontend resolve uncached p1+ images from the asset CDN.
                "image_type": work.get("AI_type") or work.get("ai_type") or r["image_type"],
                "author_id": work.get("userId") or work.get("user_id") or r["author_id"],
            }
            for r in image_rows
            if r["file_name"]
        ]
        return {"work": work, "images": images}

    return self._run(action)

def _time_range_clause(self, time_range: str) -> tuple[str, list[Any]]:
    value = str(time_range or "all").strip().lower()
    mapping = {
        "day": "-1 day",
        "week": "-7 day",
        "month": "-30 day",
        "year": "-365 day",
    }
    if value in mapping:
        return (
            "AND works.create_date >= datetime('now', ?)",
            [mapping[value]],
        )
    year_match = re.fullmatch(r"y(\d{4})", value)
    if year_match:
        return "AND substr(works.create_date, 1, 4) = ?", [year_match.group(1)]
    quarter_match = re.fullmatch(r"q(\d{4})q([1-4])", value)
    if quarter_match:
        year = int(quarter_match.group(1))
        quarter = int(quarter_match.group(2))
        start_month = 1 + (quarter - 1) * 3
        end_year = year + (1 if quarter == 4 else 0)
        end_month = 1 if quarter == 4 else start_month + 3
        return (
            "AND works.create_date >= ? AND works.create_date < ?",
            [
                f"{year:04d}-{start_month:02d}-01",
                f"{end_year:04d}-{end_month:02d}-01",
            ],
        )
    month_match = re.fullmatch(r"m(\d{4})-(\d{2})", value)
    if month_match and 1 <= int(month_match.group(2)) <= 12:
        return (
            "AND substr(works.create_date, 1, 7) = ?",
            [f"{month_match.group(1)}-{month_match.group(2)}"],
        )
    if value == "older":
        return "AND works.create_date < ?", ["2023-09-01"]
    return "", []

def _order_clause(self, sort: str, seed: int = 0) -> str:
    if sort == "random":
        # 种子哈希乱序：同一 seed 下顺序稳定（翻页/无限滚动不重复），
        # 换 seed 即换一批。SQLite 无 XOR，用乘/加移交替的整数混合打散等差条纹。
        # 模数取 2^31，保证所有中间乘积不溢出 int64（溢出会退化为 REAL 失稳）。
        m = ((int(seed) % 1999999997) + 500000003) * 2 + 1  # 恒奇且随 seed 唯一
        x = f"(works.id * {m}) % 2147483648"
        x = f"({x} + ({x} >> 11)) % 2147483648"
        x = f"({x} * 2246822519) % 2147483648"
        x = f"({x} + ({x} >> 13)) % 2147483648"
        return f"ORDER BY {x}, works.id"
    if sort == "monthly":
        return "ORDER BY works.total_bookmarks DESC, works.create_date DESC, works.id DESC"
    if sort == "count":
        return (
            "ORDER BY COALESCE(works.image_count, 0) DESC, "
            "works.create_date DESC, works.id DESC"
        )
    if sort == "old":
        return "ORDER BY works.create_date ASC, works.id ASC"
    if sort == "title":
        return (
            "ORDER BY LOWER(COALESCE(works.title, '')) COLLATE NOCASE ASC, "
            "works.create_date DESC, works.id DESC"
        )
    if sort == "group":
        return (
            "ORDER BY LOWER(COALESCE(json_extract(works.list_json, '$.group_key'), '')) "
            "COLLATE NOCASE ASC, works.create_date DESC, works.id DESC"
        )
    if sort == "author":
        return (
            "ORDER BY LOWER(COALESCE(json_extract(works.list_json, '$.account_key'), '')) "
            "COLLATE NOCASE ASC, works.create_date DESC, works.id DESC"
        )
    return "ORDER BY works.create_date DESC, works.id DESC"

def search_works(
    self,
    q: str = "",
    prompt: str = "",
    page: int = 1,
    page_size: int = 60,
    sort: str = "new",
    time_range: str = "all",
    local_scope: str = "",
    skip_total: bool = False,
    nai_only: bool = False,
    group: str = "",
    nai_facets: dict[str, str | list[str]] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    return self._search_works_impl(
        q=q,
        prompt=prompt,
        page=page,
        page_size=page_size,
        sort=sort,
        time_range=time_range,
        local_scope=local_scope,
        skip_total=skip_total,
        nai_only=nai_only,
        group=group,
        nai_facets=nai_facets,
        seed=seed,
    )

def _search_works_impl(
    self,
    q: str = "",
    prompt: str = "",
    page: int = 1,
    page_size: int = 60,
    sort: str = "new",
    time_range: str = "all",
    local_scope: str = "",
    skip_total: bool = False,
    nai_only: bool = False,
    group: str = "",
    nai_facets: dict[str, str | list[str]] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    params: list[Any] = []
    filters: list[str] = []

    scope_clause, scope_params = self._local_dataset_clause(local_scope)
    if scope_clause:
        filters.append(scope_clause)
        params.extend(scope_params)

    if nai_only:
        filters.append("LOWER(TRIM(COALESCE(works.ai_type, ''))) IN ('nai', 'nai_x')")

    facet_filters, facet_params = build_nai_facet_filter(nai_facets)
    filters.extend(facet_filters)
    params.extend(facet_params)

    group_filter = str(group or "").strip()
    if group_filter.startswith("group:"):
        filters.append("json_extract(works.list_json, '$.group_key') = ?")
        params.append(group_filter.split(":", 1)[1])
    elif group_filter.startswith("account:"):
        parts = group_filter.split(":", 2)
        if len(parts) == 3:
            filters.append("json_extract(works.list_json, '$.group_key') = ?")
            filters.append("json_extract(works.list_json, '$.account_key') = ?")
            params.extend(parts[1:3])
    elif group_filter:
        # Codex / drop folders store the name on category and group_key.
        filters.append(
            "("
            "json_extract(works.list_json, '$.group_key') = ? OR "
            "json_extract(works.list_json, '$.category') = ?"
            ")"
        )
        params.extend((group_filter, group_filter))

    # Support direct numeric search for work id (pid) or author id (user_id) by adding explicit id/user_id clause.
    # FTS only indexes text fields; numbers aren't there so pure ID entry wouldn't match otherwise.
    q_for_fts = str(q or '')
    numeric_id_terms = [int(m) for m in re.findall(r'\b(\d{5,})\b', q_for_fts)]
    if numeric_id_terms:
        for nid in numeric_id_terms:
            q_for_fts = re.sub(r'\b' + str(nid) + r'\b', '', q_for_fts)
    works_match, works_excludes = build_works_fts_query(q_for_fts.strip())
    if works_match:
        filters.append(
            "works.id IN (SELECT work_id FROM works_fts WHERE works_fts MATCH ?)"
        )
        params.append(works_match)
    for term in works_excludes:
        filters.append(
            """
            LOWER(
                COALESCE(works.title, '') || ' ' ||
                COALESCE(works.caption, '') || ' ' ||
                COALESCE(works.tags, '') || ' ' ||
                COALESCE(works.ai_type, '')
            ) NOT LIKE ?
            """
        )
        params.append(f"%{term.lower()}%")

    if numeric_id_terms:
        ph = ','.join('?' * len(numeric_id_terms))
        filters.append(f'(works.id IN ({ph}) OR works.user_id IN ({ph}))')
        params.extend(numeric_id_terms * 2)

    prompt_match, prompt_excludes = build_prompt_fts_query(prompt)
    if prompt_match:
        prompt_table = self.prompt_search_table()
        filters.append(
            f"works.id IN (SELECT work_id FROM {prompt_table} "
            f"WHERE {prompt_table} MATCH ?)"
        )
        params.append(prompt_match)
    for term in prompt_excludes:
        filters.append(
            """
            NOT EXISTS (
                SELECT 1 FROM work_images wi
                WHERE wi.work_id = works.id
                  AND LOWER(COALESCE(wi.prompt_text, '')) LIKE ?
            )
            """
        )
        params.append(f"%{term.lower()}%")

    time_sql, time_params = self._time_range_clause(time_range)
    if time_sql:
        filters.append(time_sql.replace("AND ", "", 1))
        params.extend(time_params)

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    order_sql = self._order_clause(sort, seed)
    conn = self._reader()

    has_text_query = bool(q.strip() or prompt.strip())
    use_cached_total = (
        not skip_total
        and not has_text_query
        and time_range == "all"
        and local_scope
        and not facet_filters
    )
    if skip_total or has_text_query:
        total = None
    elif use_cached_total:
        total = self.cached_scope_total(local_scope)
    else:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM works {where_sql}",
            params,
        ).fetchone()["c"]

    offset = max(page - 1, 0) * page_size
    # 先只查 id；FTS 用 IN 子查询，避免 prompt 多行 JOIN + DISTINCT 全表排序
    id_rows = conn.execute(
        f"""
        SELECT works.id
        FROM works
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()
    ids = [int(row["id"]) for row in id_rows]

    rows: list[sqlite3.Row] = []
    if ids:
        placeholders = ",".join("?" * len(ids))
        payload_rows = conn.execute(
            f"""
            SELECT works.id, works.list_json, works.detail_json,
                   works.preview_path, works.preview_downloaded,
                   works.image_count, works.total_view, works.total_bookmarks
            FROM works
            WHERE works.id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        order_map = {work_id: idx for idx, work_id in enumerate(ids)}
        rows = sorted(
            payload_rows,
            key=lambda row: order_map[int(row["id"])],
        )

    items: list[dict[str, Any]] = []
    for row in rows:
        if row["list_json"]:
            work = json.loads(row["list_json"])
        elif row["detail_json"]:
            detail = json.loads(decompress_if_needed(row["detail_json"]))
            work = detail.get("work") or {}
        else:
            continue
        work = self._hydrate_work_item(work, row)
        thumb = self.thumb_rel_path(work, row["preview_path"])
        if thumb:
            work["thumb_path"] = thumb
        work["preview_local"] = bool(row["preview_downloaded"])
        _mark_partial_list_item(work)
        items.append(work)

    return {
        "page": page,
        "page_size": page_size,
        "items": items,
        "total": total,
    }

def search_favorite_works(
    self,
    work_ids: list[int],
    *,
    q: str = "",
    page: int = 1,
    page_size: int = 60,
) -> dict[str, Any]:
    ids = [int(x) for x in work_ids if int(x) > 0]
    if not ids:
        return {"page": page, "page_size": page_size, "total": 0, "items": []}

    params: list[Any] = []
    filters: list[str] = [f"works.id IN ({','.join('?' * len(ids))})"]
    params.extend(ids)

    # Support numeric id/author in q for favorites search too
    numeric_id_terms = [int(m) for m in re.findall(r'\b(\d{5,})\b', str(q or ''))]
    if numeric_id_terms:
        ph = ','.join('?' * len(numeric_id_terms))
        filters.append(f'(works.id IN ({ph}) OR works.user_id IN ({ph}))')
        params.extend(numeric_id_terms * 2)

    works_match, works_excludes = build_works_fts_query(q)
    if works_match:
        filters.append(
            "works.id IN (SELECT work_id FROM works_fts WHERE works_fts MATCH ?)"
        )
        params.append(works_match)
    for term in works_excludes:
        filters.append(
            """
            LOWER(
                COALESCE(works.title, '') || ' ' ||
                COALESCE(works.caption, '') || ' ' ||
                COALESCE(works.tags, '') || ' ' ||
                COALESCE(works.ai_type, '')
            ) NOT LIKE ?
            """
        )
        params.append(f"%{term.lower()}%")

    where_sql = f"WHERE {' AND '.join(filters)}"
    conn = self._reader()
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM works {where_sql}",
        params,
    ).fetchone()["c"]

    offset = max(page - 1, 0) * page_size
    id_rows = conn.execute(
        f"""
        SELECT works.id
        FROM works
        {where_sql}
        ORDER BY works.create_date DESC, works.id DESC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()
    page_ids = [int(row["id"]) for row in id_rows]

    rows: list[sqlite3.Row] = []
    if page_ids:
        placeholders = ",".join("?" * len(page_ids))
        payload_rows = conn.execute(
                f"""
                SELECT works.id, works.list_json, works.detail_json,
                       works.preview_path, works.preview_downloaded,
                       works.image_count, works.total_view, works.total_bookmarks
                FROM works
                WHERE works.id IN ({placeholders})
                """,
                page_ids,
        ).fetchall()
        order_map = {work_id: idx for idx, work_id in enumerate(page_ids)}
        rows = sorted(
            payload_rows,
            key=lambda row: order_map[int(row["id"])],
        )

    items: list[dict[str, Any]] = []
    for row in rows:
        if row["list_json"]:
            work = json.loads(row["list_json"])
        elif row["detail_json"]:
            detail = json.loads(decompress_if_needed(row["detail_json"]))
            work = detail.get("work") or {}
        else:
            continue
        work = self._hydrate_work_item(work, row)
        thumb = self.thumb_rel_path(work, row["preview_path"])
        if thumb:
            work["thumb_path"] = thumb
        work["preview_local"] = bool(row["preview_downloaded"])
        items.append(work)

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
    }

@staticmethod
def _normalize_rank_period(period: str = "", *, month: str = "") -> str:
    raw = str(month or period or "current").strip().lower()
    if raw in {"", "current"}:
        return datetime.now().strftime("%Y-%m")
    if raw == "older":
        return "older"
    m = re.fullmatch(r"(\d{4})-(\d{2})", raw)
    if m:
        year = int(m.group(1))
        mon = int(m.group(2))
        if 1 <= mon <= 12:
            return f"{year:04d}-{mon:02d}"
    raise ValueError(f"无效的月榜 period/month: {month or period}")

@staticmethod
def _month_rank_clause(period_key: str) -> tuple[str, list[Any]]:
    if period_key == "older":
        return (
            "works.create_date IS NOT NULL AND works.create_date < ?",
            ["2023-09-01"],
        )
    return (
        "works.create_date IS NOT NULL AND substr(works.create_date, 1, 7) = ?",
        [period_key],
    )

def list_rank_calendar(self) -> dict[str, list[Any]]:
    def action() -> dict[str, list[Any]]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT substr(create_date, 1, 4) AS year
            FROM works
            WHERE create_date IS NOT NULL
              AND length(create_date) >= 7
            ORDER BY year DESC
            """
        ).fetchall()
        years = [int(row["year"]) for row in rows if row["year"]]
        month_rows = self.conn.execute(
            """
            SELECT DISTINCT substr(create_date, 1, 7) AS ym
            FROM works
            WHERE create_date IS NOT NULL
              AND length(create_date) >= 7
              AND substr(create_date, 1, 7) >= '2023-11'
            ORDER BY ym DESC
            """
        ).fetchall()
        months = [str(row["ym"]) for row in month_rows if row["ym"]]
        return {"years": years, "months": months}

    return self._run(action)

def search_monthly_rank(
    self,
    *,
    period: str = "current",
    month: str = "",
    q: str = "",
    prompt: str = "",
    page: int = 1,
    page_size: int = 60,
    local_scope: str = "",
    skip_total: bool = False,
    nai_only: bool = False,
) -> dict[str, Any]:
    period_key = self._normalize_rank_period(period, month=month)
    return self._search_monthly_rank_impl(
        period_key=period_key,
        q=q,
        prompt=prompt,
        page=page,
        page_size=page_size,
        local_scope=local_scope,
        skip_total=skip_total,
        nai_only=nai_only,
    )

def _search_monthly_rank_impl(
    self,
    *,
    period_key: str,
    q: str = "",
    prompt: str = "",
    page: int = 1,
    page_size: int = 60,
    local_scope: str = "",
    skip_total: bool = False,
    nai_only: bool = False,
) -> dict[str, Any]:
    params: list[Any] = []
    filters: list[str] = []

    scope_clause, scope_params = self._local_dataset_clause(local_scope)
    if scope_clause:
        filters.append(scope_clause)
        params.extend(scope_params)

    if nai_only:
        filters.append("LOWER(TRIM(COALESCE(works.ai_type, ''))) IN ('nai', 'nai_x')")

    month_sql, month_params = self._month_rank_clause(period_key)
    filters.append(month_sql)
    params.extend(month_params)

    works_match, works_excludes = build_works_fts_query(q)
    if works_match:
        filters.append(
            "works.id IN (SELECT work_id FROM works_fts WHERE works_fts MATCH ?)"
        )
        params.append(works_match)
    for term in works_excludes:
        filters.append(
            """
            LOWER(
                COALESCE(works.title, '') || ' ' ||
                COALESCE(works.caption, '') || ' ' ||
                COALESCE(works.tags, '') || ' ' ||
                COALESCE(works.ai_type, '')
            ) NOT LIKE ?
            """
        )
        params.append(f"%{term.lower()}%")

    prompt_match, prompt_excludes = build_prompt_fts_query(prompt)
    if prompt_match:
        filters.append(
            "works.id IN (SELECT work_id FROM prompt_fts WHERE prompt_fts MATCH ?)"
        )
        params.append(prompt_match)
    for term in prompt_excludes:
        filters.append(
            """
            NOT EXISTS (
                SELECT 1 FROM work_images wi
                WHERE wi.work_id = works.id
                  AND LOWER(COALESCE(wi.prompt_text, '')) LIKE ?
            )
            """
        )
        params.append(f"%{term.lower()}%")

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    order_sql = (
        "ORDER BY COALESCE(works.total_bookmarks, 0) DESC, "
        "works.create_date DESC, works.id DESC"
    )
    conn = self._reader()

    has_text_query = bool(q.strip() or prompt.strip())
    if skip_total or has_text_query:
        total = None
    else:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM works {where_sql}",
            params,
        ).fetchone()["c"]

    offset = max(page - 1, 0) * page_size
    id_rows = conn.execute(
        f"""
        SELECT works.id
        FROM works
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()
    ids = [int(row["id"]) for row in id_rows]

    rows: list[sqlite3.Row] = []
    if ids:
        placeholders = ",".join("?" * len(ids))
        payload_rows = conn.execute(
            f"""
            SELECT works.id, works.list_json, works.detail_json,
                   works.preview_path, works.preview_downloaded,
                   works.image_count, works.total_view, works.total_bookmarks
            FROM works
            WHERE works.id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        order_map = {work_id: idx for idx, work_id in enumerate(ids)}
        rows = sorted(
            payload_rows,
            key=lambda row: order_map[int(row["id"])],
        )

    items: list[dict[str, Any]] = []
    for row in rows:
        if row["list_json"]:
            work = json.loads(row["list_json"])
        elif row["detail_json"]:
            detail = json.loads(decompress_if_needed(row["detail_json"]))
            work = detail.get("work") or {}
        else:
            continue
        work = self._hydrate_work_item(work, row)
        thumb = self.thumb_rel_path(work, row["preview_path"])
        if thumb:
            work["thumb_path"] = thumb
        work["preview_local"] = bool(row["preview_downloaded"])
        items.append(work)

    return {
        "page": page,
        "page_size": page_size,
        "items": items,
        "period": period_key,
        "rank_mode": "monthly",
        "total": total,
    }

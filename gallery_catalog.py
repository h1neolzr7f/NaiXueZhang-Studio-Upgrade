"""NAI 专用三分类图库：网站 / 自选 / Q群，分库存放。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import threading
from typing import Any

from db import Database
from paths import data_dir, project_root

GALLERY_SITE = "site"
GALLERY_CODEX = "codex"
GALLERY_QQ = "qqgroup"

GALLERY_IDS = (GALLERY_SITE, GALLERY_CODEX, GALLERY_QQ)

DEFAULT_GALLERY = GALLERY_SITE
JAVASCRIPT_MAX_SAFE_INTEGER = (2**53) - 1
PRIVATE_GALLERY_PAYLOAD_KEYS = frozenset(
    {
        "source_path",
        "database_path",
        "db_path",
        "images_dir",
        "absolute_path",
        "source_url",
        "original_urls",
        "source_original_urls",
        "source_sha256",
    }
)


@dataclass(frozen=True)
class GallerySpec:
    id: str
    label_zh: str
    label_en: str
    description_zh: str
    description_en: str
    db_path: Path
    images_dir: Path
    asset_base_url: str
    cdn_fallback: bool
    # 空字符串 = 不过滤 scope（库内已是 NAI 资产）
    local_scope: str
    group_by: str | None = None  # qqgroup -> account


_DB_CACHE: dict[str, Database] = {}
_DB_CACHE_LOCK = threading.RLock()


def _root_data() -> Path:
    return data_dir(project_root())


def gallery_specs() -> dict[str, GallerySpec]:
    data = _root_data()
    galleries = data / "galleries"
    return {
        GALLERY_SITE: GallerySpec(
            id=GALLERY_SITE,
            label_zh="Pixiv NAI 图库",
            label_en="Pixiv NAI Gallery",
            description_zh="从 Pixiv 直连采集并经本地元数据验证的 NovelAI 作品。",
            description_en="NovelAI works discovered on Pixiv and verified locally from image metadata.",
            db_path=data / "aitag.db",
            images_dir=data / "images",
            asset_base_url="/data/images/",
            cdn_fallback=False,
            local_scope="local",
            group_by=None,
        ),
        GALLERY_CODEX: GallerySpec(
            id=GALLERY_CODEX,
            label_zh="自选库",
            label_en="Custom Gallery",
            description_zh="本地拖入导入的自选 NovelAI 图片，按小类归档。",
            description_en="Self-picked NovelAI images imported locally and grouped by category.",
            db_path=galleries / "codex" / "gallery.db",
            images_dir=galleries / "codex" / "images",
            asset_base_url="/data/gallery/codex/",
            cdn_fallback=False,
            local_scope="",
            group_by="category",
        ),
        GALLERY_QQ: GallerySpec(
            id=GALLERY_QQ,
            label_zh="Q群图库",
            label_en="QQ Group Gallery",
            description_zh="仅收元数据可解析的 NAI 群图，按群组和账号分层。",
            description_en="Metadata-verified NAI assets grouped by QQ group and account.",
            db_path=galleries / "qqgroup" / "gallery.db",
            images_dir=galleries / "qqgroup" / "images",
            asset_base_url="/data/gallery/qqgroup/",
            cdn_fallback=False,
            local_scope="",
            group_by="account",
        ),
    }


def normalize_gallery_id(raw: str | None) -> str:
    value = str(raw or DEFAULT_GALLERY).strip().lower()
    if value in {"website", "web", "aitag"}:
        return GALLERY_SITE
    if value in {"law", "director", "所长法典", "法典", "自选", "自选库"}:
        return GALLERY_CODEX
    if value in {"qq", "qun", "group", "q群", "qq群"}:
        return GALLERY_QQ
    if value in GALLERY_IDS:
        return value
    return DEFAULT_GALLERY


def serialize_gallery_payload(
    payload: Any,
    gallery_id: str | None = None,
    *,
    _key: str = "",
) -> Any:
    """Return a JSON-safe gallery payload without losing opaque identifiers.

    Historical QQ imports can contain 64-bit work IDs.  JSON itself preserves
    the digits, but JavaScript parses numeric tokens as IEEE-754 doubles before
    application code can intervene.  QQ work identifiers are therefore text at
    the API seam, and any integer outside JavaScript's safe range is text for
    every gallery.
    """

    gid = normalize_gallery_id(gallery_id)
    if isinstance(payload, dict):
        return {
            key: serialize_gallery_payload(value, gid, _key=str(key))
            for key, value in payload.items()
            if str(key) not in PRIVATE_GALLERY_PAYLOAD_KEYS
        }
    if isinstance(payload, list):
        return [
            serialize_gallery_payload(value, gid, _key=_key)
            for value in payload
        ]
    if isinstance(payload, tuple):
        return [
            serialize_gallery_payload(value, gid, _key=_key)
            for value in payload
        ]
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, int) and (
        abs(payload) > JAVASCRIPT_MAX_SAFE_INTEGER
        or (gid == GALLERY_QQ and _key in {"id", "work_id"})
    ):
        return str(payload)
    return payload


def get_spec(gallery_id: str | None = None) -> GallerySpec:
    gid = normalize_gallery_id(gallery_id)
    return gallery_specs()[gid]


def ensure_gallery_dirs(gallery_id: str | None = None) -> GallerySpec:
    spec = get_spec(gallery_id)
    spec.db_path.parent.mkdir(parents=True, exist_ok=True)
    spec.images_dir.mkdir(parents=True, exist_ok=True)
    return spec


def get_db(gallery_id: str | None = None) -> Database:
    gid = normalize_gallery_id(gallery_id)
    with _DB_CACHE_LOCK:
        cached = _DB_CACHE.get(gid)
        if cached is not None:
            return cached
        spec = ensure_gallery_dirs(gid)
        db = Database(spec.db_path)
        _DB_CACHE[gid] = db
        return db


def close_all_gallery_dbs() -> None:
    with _DB_CACHE_LOCK:
        for db in list(_DB_CACHE.values()):
            try:
                db.close()
            except Exception:
                pass
        _DB_CACHE.clear()


def public_gallery_list() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for gid in GALLERY_IDS:
        spec = get_spec(gid)
        db = get_db(gid)
        try:
            total = int(db.count_works())
        except Exception:
            total = 0
        out.append(
            {
                "id": spec.id,
                "label_zh": spec.label_zh,
                "label_en": spec.label_en,
                "description_zh": spec.description_zh,
                "description_en": spec.description_en,
                "asset_base_url": spec.asset_base_url,
                "cdn_fallback": spec.cdn_fallback,
                "group_by": spec.group_by,
                "total_works": total,
            }
        )
    return out


def _cached_group_index(raw: str, spec) -> list[dict[str, Any]] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    if spec.group_by == "category" and not any(
        isinstance(item, dict) and item.get("kind") == "folder" for item in data
    ):
        return None
    if spec.group_by == "account":
        has_local_drop = any(
            isinstance(item, dict) and item.get("account_key") == "local-drop"
            for item in data
        )
        has_folder = any(
            isinstance(item, dict) and item.get("kind") == "folder"
            for item in data
        )
        if has_local_drop and not has_folder:
            return None
    return data


def _build_group_index(rows, spec) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    group_counts: dict[str, int] = {}
    group_labels: dict[str, str] = {}
    account_counts: dict[tuple[str, str], int] = {}
    account_labels: dict[tuple[str, str], str] = {}
    for row in rows:
        try:
            item = json.loads(row["list_json"] or "{}")
        except Exception:
            item = {}
        if spec.group_by == "account":
            group_key = str(item.get("group_key") or "legacy")
            group_label = str(
                item.get("group_label")
                or ("历史未分组" if group_key == "legacy" else group_key)
            )
            key = str(item.get("account_key") or item.get("userId") or row["user_id"] or "")
            label = str(item.get("account_label") or key)
            if not key:
                continue
            pair = (group_key, key)
            group_counts[group_key] = group_counts.get(group_key, 0) + 1
            group_labels[group_key] = group_label
            account_counts[pair] = account_counts.get(pair, 0) + 1
            account_labels[pair] = label or key
            continue
        key = str(
            item.get("category")
            or item.get("group_key")
            or (row["tags"] or "").split(",")[0]
            or "未分类"
        )
        label = str(item.get("group_label") or key)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        labels[key] = label or key
    if spec.group_by == "account":
        hierarchy: list[dict[str, Any]] = []
        for group_key in sorted(
            group_counts,
            key=lambda value: (-group_counts[value], group_labels[value]),
        ):
            parent_key = f"group:{group_key}"
            hierarchy.append(
                {
                    "key": parent_key,
                    "label": group_labels[group_key],
                    "count": group_counts[group_key],
                    "kind": "group",
                    "group_key": group_key,
                }
            )
            members = [pair for pair in account_counts if pair[0] == group_key]
            drop_only = bool(members) and all(pair[1] == "local-drop" for pair in members)
            hierarchy[-1]["kind"] = "folder" if drop_only else "group"
            if drop_only:
                continue
            for pair in sorted(
                members,
                key=lambda value: (-account_counts[value], account_labels[value]),
            ):
                account_key = pair[1]
                hierarchy.append(
                    {
                        "key": f"account:{group_key}:{account_key}",
                        "label": account_labels[pair],
                        "count": account_counts[pair],
                        "kind": "account",
                        "parent_key": parent_key,
                        "group_key": group_key,
                        "account_key": account_key,
                    }
                )
        return hierarchy
    return [
        {
            "key": f"group:{k}",
            "label": labels.get(k, k),
            "count": counts[k],
            "kind": "folder",
            "group_key": k,
        }
        for k in sorted(counts.keys(), key=lambda x: (-counts[x], x))
    ]


def list_group_keys(gallery_id: str) -> list[dict[str, Any]]:
    """Q群按账号、自选库按分类统计。"""
    gid = normalize_gallery_id(gallery_id)
    spec = get_spec(gid)
    if not spec.group_by:
        return []
    db = get_db(gid)
    cached = _cached_group_index(db.get_state(f"group_index:{gid}", ""), spec)
    if cached is not None:
        return cached

    def scan() -> list[dict[str, Any]]:
        row = db.conn.execute(
            "SELECT value FROM crawl_state WHERE key = ?",
            (f"group_index:{gid}",),
        ).fetchone()
        again = _cached_group_index(row["value"] if row else "", spec)
        if again is not None:
            return again
        rows = db.conn.execute(
            "SELECT id, user_id, tags, list_json FROM works"
        ).fetchall()
        items = _build_group_index(rows, spec)
        db.conn.execute(
            "INSERT INTO crawl_state(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"group_index:{gid}", json.dumps(items, ensure_ascii=False)),
        )
        db.conn.commit()
        return items

    return db._run(scan)

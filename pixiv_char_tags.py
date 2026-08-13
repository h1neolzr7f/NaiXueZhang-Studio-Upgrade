"""Danbooru 明日方舟角色 tag → Pixiv 日文角色 tag（例：プリースティス(アークナイツ)）。"""

from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from paths import data_dir, seed_data_file

ROOT = Path(__file__).resolve().parent
DATA_DIR: Path | None = None


def _data() -> Path:
    return Path(DATA_DIR) if DATA_DIR is not None else data_dir()


def _seed(name: str) -> Path:
    return (_data() / name) if DATA_DIR is not None else seed_data_file(name)


def _library_path() -> Path:
    return _data() / "ark_char_library.json"


def _char_swap_path() -> Path:
    return _data() / "char_swap_config.json"


def _local_db_path() -> Path:
    return _data() / "aitag.db"

ARK_SUFFIX_RE = re.compile(r"^(.+)_\(([^)]+)\)$", re.IGNORECASE)
_KATAKANA_RE = re.compile(r"[\u30a0-\u30ff]")
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
_JP_ARK_SUFFIX_RE = re.compile(r"^(.+)\(アークナイツ\)$")

_BAD_JP_INNER = frozenset(
    {
        "w",
        "doc",
        "logos",
        "medic",
        "mon3tr",
        "u-official",
        "ai",
        "r-18",
    }
)


def _normalize_danbooru_tag(tag: str) -> str:
    return str(tag or "").strip().lower()


def _humanize_inner(inner: str) -> str:
    return str(inner or "").replace("_", " ").strip().lower()


def _is_quality_jp_ark_tag(jp_tag: str) -> bool:
    m = _JP_ARK_SUFFIX_RE.match(str(jp_tag or "").strip())
    if not m:
        return False
    inner = m.group(1).strip()
    if not inner or inner.lower() in _BAD_JP_INNER:
        return False
    kata = len(_KATAKANA_RE.findall(inner))
    latin = len(re.findall(r"[A-Za-z]", inner))
    if kata < 2:
        return False
    if latin > kata:
        return False
    return True


def _pick_best_jp_for_zh(zh: str, zh_to_jp: dict[str, list[str]]) -> str:
    candidates = [jp for jp in (zh_to_jp.get(zh) or []) if _is_quality_jp_ark_tag(jp)]
    if not candidates:
        return ""
    return max(
        candidates,
        key=lambda jp: (
            len(_KATAKANA_RE.findall(_JP_ARK_SUFFIX_RE.match(jp).group(1))),
            len(jp),
        ),
    )


@lru_cache(maxsize=1)
def _load_zh_to_jp() -> dict[str, list[str]]:
    path = _seed("tag_dict.json")
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, list[str]] = {}
    for jp, zh in (raw or {}).items():
        jp_s = str(jp or "").strip()
        zh_s = str(zh or "").strip()
        if not jp_s or not zh_s or not _is_quality_jp_ark_tag(jp_s):
            continue
        if not _CHINESE_RE.search(zh_s) or len(zh_s) > 12:
            continue
        out.setdefault(zh_s, []).append(jp_s)
    return out


def _load_manual_maps() -> tuple[dict[str, str], dict[str, str]]:
    zh_map: dict[str, str] = {}
    ja_map: dict[str, str] = {}
    path = _seed("pixiv_general_jp.json")
    if not path.exists():
        return zh_map, ja_map
    try:
        lex = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return zh_map, ja_map
    for key, value in (lex.get("character_zh") or {}).items():
        low = _normalize_danbooru_tag(key)
        text = str(value or "").strip()
        if low and text:
            zh_map[low] = text
    for key, value in (lex.get("character_ja") or {}).items():
        low = _normalize_danbooru_tag(key)
        text = str(value or "").strip()
        if low and text:
            ja_map[low] = text
    return zh_map, ja_map


def _load_preset_zh_maps() -> dict[str, str]:
    out: dict[str, str] = {}

    def _ingest(items: list[Any] | None) -> None:
        for item in items or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            if not label or not _CHINESE_RE.search(label):
                continue
            for tag in item.get("identity") or []:
                low = _normalize_danbooru_tag(tag)
                if low.endswith("_(arknights)"):
                    out.setdefault(low, label)

    for path in (_seed("char_presets.json"), _char_swap_path()):
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for bucket in ("female", "male"):
            _ingest(raw.get(bucket))
        _ingest((raw.get("custom") or {}).get("female"))
        _ingest((raw.get("custom") or {}).get("male"))

    if _library_path().exists():
        try:
            lib = json.loads(_library_path().read_text(encoding="utf-8"))
            for bucket in ("female", "male"):
                for item in lib.get(bucket) or []:
                    if not isinstance(item, dict):
                        continue
                    tag = _normalize_danbooru_tag(item.get("tag") or "")
                    label = str(item.get("label") or "").strip()
                    if tag.endswith("_(arknights)") and _CHINESE_RE.search(label):
                        out.setdefault(tag, label)
        except Exception:
            pass
    return out


def _mine_en_zh_pairs(*, min_count: int = 3) -> dict[str, str]:
    db_path = _local_db_path()
    if not db_path.exists():
        return {}
    pair_counts: dict[str, dict[str, int]] = {}
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT tags FROM works WHERE tags IS NOT NULL").fetchall()
    conn.close()

    for (raw,) in rows:
        try:
            tags = json.loads(raw)
            if not isinstance(tags, list):
                continue
        except Exception:
            continue
        en_keys: list[str] = []
        cn_tags: list[str] = []
        for tag in tags:
            text = str(tag or "").strip()
            if not text:
                continue
            if re.match(r"^[A-Z][a-zA-Z'.]+$", text):
                en_keys.append(text.lower().replace(" ", "_"))
            if (
                _CHINESE_RE.search(text)
                and 2 <= len(text) <= 8
                and "明日方舟" not in text
                and "/" not in text
            ):
                cn_tags.append(text)
        if not en_keys or not cn_tags:
            continue
        for en in en_keys:
            bucket = pair_counts.setdefault(en, {})
            for cn in cn_tags:
                bucket[cn] = bucket.get(cn, 0) + 1

    zh_to_jp = _load_zh_to_jp()
    out: dict[str, str] = {}
    for en, counts in pair_counts.items():
        ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0])))
        for zh, count in ranked:
            if count < min_count:
                break
            if _pick_best_jp_for_zh(zh, zh_to_jp):
                out[en] = zh
                break
    return out


@lru_cache(maxsize=1)
def _load_danbooru_to_zh() -> dict[str, str]:
    manual_zh, _ = _load_manual_maps()
    preset_zh = _load_preset_zh_maps()
    mined_en_zh = _mine_en_zh_pairs()
    zh_to_jp = _load_zh_to_jp()

    out: dict[str, str] = {}
    if _library_path().exists():
        try:
            lib = json.loads(_library_path().read_text(encoding="utf-8"))
            for bucket in ("female", "male"):
                for item in lib.get(bucket) or []:
                    if not isinstance(item, dict):
                        continue
                    tag = _normalize_danbooru_tag(item.get("tag") or "")
                    if not tag.endswith("_(arknights)"):
                        continue
                    inner = tag.replace("_(arknights)", "")
                    label = str(item.get("label") or "").strip()
                    zh = ""
                    if manual_zh.get(tag):
                        zh = manual_zh[tag]
                    elif preset_zh.get(tag):
                        zh = preset_zh[tag]
                    elif _CHINESE_RE.search(label):
                        zh = label
                    elif inner in mined_en_zh:
                        zh = mined_en_zh[inner]
                    else:
                        lab_key = _humanize_inner(label).replace(" ", "_")
                        zh = mined_en_zh.get(lab_key, "")
                    if zh and _pick_best_jp_for_zh(zh, zh_to_jp):
                        out[tag] = zh
        except Exception:
            pass

    for tag, zh in manual_zh.items():
        if zh and _pick_best_jp_for_zh(zh, zh_to_jp):
            out[tag] = zh
    for tag, zh in preset_zh.items():
        if zh and _pick_best_jp_for_zh(zh, zh_to_jp):
            out.setdefault(tag, zh)
    return out


@lru_cache(maxsize=1)
def _load_danbooru_to_ja() -> dict[str, str]:
    _, manual_ja = _load_manual_maps()
    zh_to_jp = _load_zh_to_jp()
    danbooru_to_zh = _load_danbooru_to_zh()
    out = dict(manual_ja)
    for tag, zh in danbooru_to_zh.items():
        jp = _pick_best_jp_for_zh(zh, zh_to_jp)
        if jp:
            out.setdefault(tag, jp)
    return out


def reload_ark_char_pixiv_maps() -> dict[str, int]:
    _load_zh_to_jp.cache_clear()
    _load_danbooru_to_zh.cache_clear()
    _load_danbooru_to_ja.cache_clear()
    return {
        "danbooru_zh": len(_load_danbooru_to_zh()),
        "danbooru_ja": len(_load_danbooru_to_ja()),
    }


def resolve_ark_char_pixiv_tags(danbooru_tag: str) -> tuple[str, str]:
    """返回 (中文角色名, Pixiv 日文 tag)。无匹配时返回空字符串。"""
    low = _normalize_danbooru_tag(danbooru_tag)
    if not low:
        return "", ""
    manual_zh, manual_ja = _load_manual_maps()
    zh_to_jp = _load_zh_to_jp()
    danbooru_to_zh = _load_danbooru_to_zh()
    danbooru_to_ja = _load_danbooru_to_ja()

    zh = manual_zh.get(low) or danbooru_to_zh.get(low, "")
    ja = manual_ja.get(low) or danbooru_to_ja.get(low, "")
    if not ja and zh:
        ja = _pick_best_jp_for_zh(zh, zh_to_jp)
    return zh, ja


def collect_ark_char_pixiv_hints(tokens: list[str]) -> tuple[list[str], list[str]]:
    """从咒语 token 中提取明日方舟角色的中英 Pixiv 标签建议。"""
    zh_hints: list[str] = []
    ja_hints: list[str] = []
    zh_seen: set[str] = set()
    ja_seen: set[str] = set()

    def _add_zh(text: str) -> None:
        if text and text not in zh_seen:
            zh_seen.add(text)
            zh_hints.append(text)

    def _add_ja(text: str) -> None:
        if text and text not in ja_seen:
            ja_seen.add(text)
            ja_hints.append(text)

    for raw in tokens or []:
        low = _normalize_danbooru_tag(raw)
        m = ARK_SUFFIX_RE.match(low)
        if not m:
            continue
        series = str(m.group(2) or "").strip().lower()
        if series != "arknights":
            continue
        zh, ja = resolve_ark_char_pixiv_tags(low)
        if zh:
            _add_zh(zh)
        if ja:
            _add_ja(ja)
    return zh_hints, ja_hints
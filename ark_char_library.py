"""明日方舟备选角色库：基于 Danbooru 角色 tag + 本地 tag 词典，按男女分类可搜索。"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
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


def _local_db_path() -> Path:
    return _data() / "aitag.db"

CHAR_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_'().-]*_\(arknights\)$", re.IGNORECASE)
SKIP_SUBSTR = (
    "infection_monitor",
    "oripathy_lesion",
    "originium",
    "logo",
    "symbol",
    "chibi",
    "cosplay",
    "crossover",
    "parody",
    "meme",
)

EXPLICIT_MALE = frozenset(
    {
        "doctor_(arknights)",
        "male_doctor_(arknights)",
        "silverash_(arknights)",
        "mountain_(arknights)",
        "executor_(arknights)",
        "executor_the_ex_foedere_commission_(arknights)",
        "thornc_(arknights)",
        "phantom_(arknights)",
        "hellagur_(arknights)",
        "leonhardt_(arknights)",
        "courier_(arknights)",
        "gnosis_(arknights)",
        "passenger_(arknights)",
        "mlynar_(arknights)",
        "hoederer_(arknights)",
        "tequila_(arknights)",
        "aosta_(arknights)",
        "matterhorn_(arknights)",
        "spot_(arknights)",
        "ansel_(arknights)",
        "adnachiel_(arknights)",
        "elysium_(arknights)",
        "enforcer_(arknights)",
        "ethan_(arknights)",
        "flamebringer_(arknights)",
        "hibiscus_(arknights)",
        "jaye_(arknights)",
        "mr.nothing_(arknights)",
        "noir_corne_(arknights)",
        "steward_(arknights)",
        "windflit_(arknights)",
        "chongyue_(arknights)",
        "zuole_(arknights)",
        "yu_(arknights)",
        "zuo_le_(arknights)",
        "lee_(arknights)",
        "qiubai_(arknights)",
        "shu_(arknights)",
        "ling_(arknights)",
        "chongyue_(arknights)",
        "jiaoqiu_(arknights)",
        "sankta_miksaparato_(arknights)",
        "vigil_(arknights)",
        "pozëmka_(arknights)",
        "pozyomka_(arknights)",
    }
)


def _load_tag_dict() -> dict[str, str]:
    path = _seed("tag_dict.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _humanize_tag(tag: str) -> str:
    base = tag.replace("_(arknights)", "").replace("_", " ").strip()
    return base.title() if base else tag


def _label_for_tag(
    tag: str,
    tag_dict: dict[str, str],
    translator: Any | None = None,
) -> str:
    low = tag.lower()
    if translator is not None:
        try:
            info = translator.translate(low)
            if info.get("translated") and info.get("zh"):
                return str(info["zh"])
        except Exception:
            pass
    if low in tag_dict and tag_dict[low]:
        return str(tag_dict[low])
    inner = low.replace("_(arknights)", "")
    ark_jp = f"{inner}(アークナイツ)"
    if ark_jp in tag_dict:
        return str(tag_dict[ark_jp])
    if inner in tag_dict:
        return str(tag_dict[inner])
    return _humanize_tag(low)


_CHINESE = re.compile(r"[\u4e00-\u9fff]")


def _should_skip(tag: str) -> bool:
    low = tag.lower()
    if not CHAR_TAG_RE.match(low):
        return True
    return any(part in low for part in SKIP_SUBSTR)


def _mine_ark_cn_labels(db_path: Path) -> dict[str, str]:
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
        ark_tags = [str(t).strip().lower() for t in tags if str(t).strip().lower().endswith("_(arknights)")]
        cn_tags = [
            str(t).strip()
            for t in tags
            if _CHINESE.search(str(t)) and 1 < len(str(t)) <= 12 and "明日方舟" not in str(t)
        ]
        if not ark_tags or not cn_tags:
            continue
        for ark in ark_tags:
            bucket = pair_counts.setdefault(ark, {})
            for cn in cn_tags:
                bucket[cn] = bucket.get(cn, 0) + 1
    out: dict[str, str] = {}
    for ark, counts in pair_counts.items():
        if not counts:
            continue
        best_cn, best_n = max(counts.items(), key=lambda item: item[1])
        if best_n >= 1:
            out[ark] = best_cn
    return out


def _mine_gender_counts(db_path: Path) -> dict[str, dict[str, int]]:
    if not db_path.exists():
        return {}
    out: dict[str, dict[str, int]] = {}
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT tags FROM works WHERE tags IS NOT NULL"
    ).fetchall()
    conn.close()
    for (raw,) in rows:
        try:
            tags = json.loads(raw)
            if not isinstance(tags, list):
                continue
        except Exception:
            continue
        lowered = [str(t).strip().lower() for t in tags if str(t).strip()]
        has_boy = any(t in {"1boy", "2boys", "3boys", "male_focus", "boys_only"} for t in lowered)
        has_girl = any(t in {"1girl", "2girls", "3girls", "female_focus", "girls_only"} for t in lowered)
        for t in lowered:
            if not t.endswith("_(arknights)"):
                continue
            bucket = out.setdefault(t, {"male": 0, "female": 0})
            if has_boy and not has_girl:
                bucket["male"] += 1
            elif has_girl and not has_boy:
                bucket["female"] += 1
    return out


def _classify_gender(tag: str, mined: dict[str, dict[str, int]]) -> str:
    low = tag.lower()
    if low in EXPLICIT_MALE or low.startswith("male_"):
        return "male"
    stats = mined.get(low) or {}
    m = int(stats.get("male") or 0)
    f = int(stats.get("female") or 0)
    if m > f and m >= 2:
        return "male"
    if f > m and f >= 1:
        return "female"
    if m > 0 and f == 0:
        return "male"
    return "female"


def _to_preset(tag: str, gender: str, label: str, posts: int) -> dict[str, Any]:
    identity = [tag.lower()]
    if gender == "male":
        identity.extend(["1boy", "male_focus"])
    else:
        identity.extend(["1girl", "female_focus"])
    return {
        "id": f"{tag.lower().replace('_(arknights)', '').replace(' ', '_')}_{gender[0]}",
        "label": label,
        "gender": gender,
        "tag": tag.lower(),
        "posts": posts,
        "identity": identity,
        "body": [],
        "appearance": [],
        "source": "ark_library",
    }


def _load_preset_label_map() -> dict[str, str]:
    labels: dict[str, str] = {}
    preset_path = _seed("char_presets.json")
    if preset_path.exists():
        try:
            raw = json.loads(preset_path.read_text(encoding="utf-8"))
            for bucket in ("female", "male"):
                for item in raw.get(bucket) or []:
                    name = str(item.get("label") or "").strip()
                    if not name:
                        continue
                    for tag in item.get("identity") or []:
                        low = str(tag).strip().lower()
                        if low:
                            labels[low] = name
        except Exception:
            pass
    try:
        from char_swap_config import load_config

        custom = load_config().get("custom_presets") or {}
        for bucket in ("female", "male"):
            for item in custom.get(bucket) or []:
                name = str(item.get("label") or "").strip()
                if not name:
                    continue
                for tag in item.get("identity") or []:
                    low = str(tag).strip().lower()
                    if low:
                        labels[low] = name
    except Exception:
        pass
    return labels


def build_library(*, force: bool = False) -> dict[str, Any]:
    library_path = _library_path()
    if library_path.exists() and not force:
        try:
            cached = json.loads(library_path.read_text(encoding="utf-8"))
            if cached.get("female") and cached.get("male"):
                return cached
        except Exception:
            pass

    from tag_translate import TagTranslator

    tag_dict = _load_tag_dict()
    translator = TagTranslator()
    preset_labels = _load_preset_label_map()
    mined = _mine_gender_counts(_local_db_path())
    cn_labels = _mine_ark_cn_labels(_local_db_path())
    chars: dict[str, int] = {}
    ark_db_path = _seed("danbooru_arknights.json")
    if ark_db_path.exists():
        try:
            raw = json.loads(ark_db_path.read_text(encoding="utf-8"))
            chars = raw.get("characters") or {}
        except Exception:
            chars = {}

    female: list[dict[str, Any]] = []
    male: list[dict[str, Any]] = []
    for tag, posts in sorted(chars.items(), key=lambda x: (-int(x[1] or 0), x[0])):
        low = str(tag).strip().lower()
        if _should_skip(low):
            continue
        gender = _classify_gender(low, mined)
        label = (
            preset_labels.get(low)
            or cn_labels.get(low)
            or _label_for_tag(low, tag_dict, translator)
        )
        preset = _to_preset(low, gender, label, int(posts or 0))
        (male if gender == "male" else female).append(preset)

    payload = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "female_count": len(female),
        "male_count": len(male),
        "female": female,
        "male": male,
    }
    library_path.parent.mkdir(parents=True, exist_ok=True)
    library_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


@lru_cache(maxsize=1)
def _library() -> dict[str, Any]:
    return build_library(force=False)


def reload_library() -> dict[str, Any]:
    _library.cache_clear()
    return build_library(force=True)


def search_library(
    *,
    gender: str | None = None,
    q: str = "",
    limit: int = 80,
) -> dict[str, Any]:
    data = _library()
    pool: list[dict[str, Any]] = []
    if gender == "male":
        pool = list(data.get("male") or [])
    elif gender == "female":
        pool = list(data.get("female") or [])
    else:
        pool = list(data.get("female") or []) + list(data.get("male") or [])

    needle = str(q or "").strip().lower()
    if needle:
        filtered = []
        for item in pool:
            hay = " ".join(
                [
                    str(item.get("label") or ""),
                    str(item.get("tag") or ""),
                    " ".join(item.get("identity") or []),
                ]
            ).lower()
            if needle in hay:
                filtered.append(item)
        pool = filtered

    limit = max(1, min(int(limit or 80), 200))
    return {
        "ok": True,
        "q": q,
        "gender": gender or "all",
        "total": len(pool),
        "built_at": data.get("built_at"),
        "female_count": data.get("female_count"),
        "male_count": data.get("male_count"),
        "items": pool[:limit],
    }


def library_stats() -> dict[str, Any]:
    data = _library()
    return {
        "ok": True,
        "built_at": data.get("built_at"),
        "female_count": data.get("female_count"),
        "male_count": data.get("male_count"),
    }
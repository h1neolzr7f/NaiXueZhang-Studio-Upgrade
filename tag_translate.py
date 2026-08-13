import json
import re
import sqlite3
from pathlib import Path

from paths import data_dir, seed_data_file

ROOT = Path(__file__).resolve().parent
DB_PATH: Path | None = None
DICT_PATH: Path | None = None
DANBOORU_REC_PATH: Path | None = None
DANBOORU_ARK_PATH: Path | None = None
CHAR_PRESETS_PATH: Path | None = None


def _db_path() -> Path:
    return Path(DB_PATH) if DB_PATH is not None else data_dir() / "aitag.db"


def _dict_path() -> Path:
    return Path(DICT_PATH) if DICT_PATH is not None else seed_data_file("tag_dict.json")


def _danbooru_rec_path() -> Path:
    return (
        Path(DANBOORU_REC_PATH)
        if DANBOORU_REC_PATH is not None
        else seed_data_file("danbooru_recognition.json")
    )


def _danbooru_ark_path() -> Path:
    return (
        Path(DANBOORU_ARK_PATH)
        if DANBOORU_ARK_PATH is not None
        else seed_data_file("danbooru_arknights.json")
    )


def _char_presets_path() -> Path:
    return (
        Path(CHAR_PRESETS_PATH)
        if CHAR_PRESETS_PATH is not None
        else seed_data_file("char_presets.json")
    )

_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_HIRAGANA_KATAKANA = re.compile(r"[\u3040-\u30ff]")
_CHINESE = re.compile(r"[\u4e00-\u9fff]")
_ARKNIGHTS_SUFFIX = re.compile(r"^(.+?)\(アークナイツ\)$")
_PAREN_SUFFIX = re.compile(r"^(.+?)\([^)]+\)$")

# 常见 Pixiv / Danbooru 日文标签
STATIC_JP_ZH: dict[str, str] = {
    "アークナイツ": "明日方舟",
    "Arknights": "明日方舟",
    "arknights": "明日方舟",
    "女の子": "女孩子",
    "少女": "少女",
    "巨乳": "巨乳",
    "極上の女体": "极上女体",
    "魅惑のふともも": "魅惑大腿",
    "魅惑の谷間": "魅惑乳沟",
    "極上の乳": "极上之胸",
    "裸足": "裸足",
    "足裏": "脚底",
    "水着": "泳装",
    "中出し": "中出",
    "フェラ": "口交",
    "パイズリ": "乳交",
    "アナル": "肛交",
    "レイプ": "强奸",
    "輪姦": "轮奸",
    "調教": "调教",
    "拘束": "束缚",
    "目隠し": "眼罩",
    "しっぽ": "尾巴",
    "獣耳": "兽耳",
    "ケモミミ": "兽耳",
    "ロリ": "萝莉",
    "メイド": "女仆",
    "制服": "制服",
    "下着": "内衣",
    "パンツ": "内裤",
    "ブラジャー": "胸罩",
    "全裸": "全裸",
    "ノーブラ": "无胸罩",
    "乳首": "乳头",
    "おっぱい": "胸部",
    "尻": "臀部",
    "太もも": "大腿",
    "横乳": "侧乳",
    "腋": "腋下",
    "舌出し": "吐舌",
    "赤面": "脸红",
    "笑顔": "笑容",
    "泣き顔": "哭泣",
    "汗": "汗",
    "濡れ": "湿润",
    "キス": "接吻",
    "抱きしめる": "拥抱",
    "座り": "坐姿",
    "立ち絵": "立绘",
    "イラスト": "插画",
    "AIイラスト": "AI插画",
    "AI生成": "AI生成",
    "AI": "AI",
    "NovelAI": "NovelAI",
    "NTR": "NTR",
    "百合": "百合",
    "ヤリ": "做爱",
    "SEX": "性爱",
    "オナニー": "自慰",
    "潮吹き": "潮吹",
    "母乳": "母乳",
    "妊娠": "怀孕",
    "腹ポテ": "孕肚",
    "ムチムチ": "丰满",
    "スレンダー": "纤细",
    "黒髪": "黑发",
    "金髪": "金发",
    "銀髪": "银发",
    "赤髪": "红发",
    "青髪": "蓝发",
    "白髪": "白发",
    "ロングヘア": "长发",
    "ショートヘア": "短发",
    "ツインテール": "双马尾",
    "ポニーテール": "马尾",
    "眼鏡": "眼镜",
    "帽子": "帽子",
    "ストッキング": "丝袜",
    "ニーハイ": "过膝袜",
    "ガarter": "吊带袜",
    "ドレス": "连衣裙",
    "スカート": "裙子",
    "ビキニ": "比基尼",
    "温泉": "温泉",
    "お風呂": "浴室",
    "ベッド": "床",
    "教室": "教室",
    "屋外": "户外",
    "夜景": "夜景",
    "桜": "樱花",
    "花嫁": "新娘",
    "悪堕ち": "恶堕",
    "拘束": "束缚",
    "縛り": "捆绑",
}


def _load_dict_file() -> dict[str, str]:
    path = _dict_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _humanize_danbooru_tag(tag: str) -> str:
    raw = str(tag or "").strip()
    if not raw:
        return ""
    base = raw
    for suffix in ("_(arknights)", "(アークナイツ)"):
        if base.lower().endswith(suffix.lower()):
            base = base[: -len(suffix)]
            break
    base = base.replace("_", " ").strip()
    if not base:
        return raw
    return " ".join(part.capitalize() for part in base.split())


def _load_danbooru_sets() -> tuple[set[str], set[str]]:
    known: set[str] = set()
    appearance: set[str] = set()
    if _danbooru_rec_path().exists():
        try:
            rec = json.loads(_danbooru_rec_path().read_text(encoding="utf-8"))
            for key in ("characters", "copyrights", "appearance", "body_extra"):
                for tag in rec.get(key) or []:
                    low = str(tag).strip().lower()
                    if low:
                        known.add(low)
            for tag in rec.get("appearance") or []:
                low = str(tag).strip().lower()
                if low:
                    appearance.add(low)
        except Exception:
            pass
    if _danbooru_ark_path().exists():
        try:
            ark = json.loads(_danbooru_ark_path().read_text(encoding="utf-8"))
            for tag in (ark.get("characters") or {}):
                low = str(tag).strip().lower()
                if low:
                    known.add(low)
            for tag in (ark.get("copyrights") or {}):
                low = str(tag).strip().lower()
                if low:
                    known.add(low)
        except Exception:
            pass
    return known, appearance


_DANBOORU_KNOWN, _DANBOORU_APPEARANCE = _load_danbooru_sets()


def _parse_tags(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _is_mostly_japanese(text: str) -> bool:
    jp = len(_HIRAGANA_KATAKANA.findall(text))
    zh = len(_CHINESE.findall(text))
    return jp > 0 and jp >= zh


def _looks_like_cn_name(text: str) -> bool:
    if not _CHINESE.search(text):
        return False
    if len(text) > 12:
        return False
    blocked = {"明日方舟", "R-18", "NovelAI", "AI", "AI生成", "AI插画"}
    return text not in blocked and not text.startswith("http")


def build_tag_dictionary(db_path: Path | None = None) -> dict[str, str]:
    mapping: dict[str, str] = dict(STATIC_JP_ZH)
    conn = sqlite3.connect(db_path or _db_path())
    rows = conn.execute("SELECT tags FROM works WHERE tags IS NOT NULL").fetchall()
    conn.close()

    # 同一作品内：日文干员 tag 与中文名 tag 互配
    pair_counts: dict[str, dict[str, int]] = {}
    for (raw,) in rows:
        tags = _parse_tags(raw)
        jp_tags = [t for t in tags if _ARKNIGHTS_SUFFIX.match(t) or _is_mostly_japanese(t)]
        cn_tags = [t for t in tags if _looks_like_cn_name(t)]
        if not jp_tags or not cn_tags:
            continue
        for jp in jp_tags:
            bucket = pair_counts.setdefault(jp, {})
            for cn in cn_tags:
                bucket[cn] = bucket.get(cn, 0) + 1

    for jp, cn_counts in pair_counts.items():
        if not cn_counts:
            continue
        best_cn, best_n = max(cn_counts.items(), key=lambda item: item[1])
        if best_n >= 2:
            mapping[jp] = best_cn
        m = _ARKNIGHTS_SUFFIX.match(jp)
        if m and best_n >= 1:
            mapping[jp] = best_cn
            mapping[m.group(1)] = best_cn

    # 已有中文标签直接映射自身
    all_tags: set[str] = set()
    for (raw,) in rows:
        all_tags.update(_parse_tags(raw))
    for tag in all_tags:
        if _CHINESE.search(tag) and tag not in mapping:
            mapping[tag] = tag
        if tag in STATIC_JP_ZH:
            mapping[tag] = STATIC_JP_ZH[tag]

    return mapping


def save_tag_dictionary(path: Path | None = None, db_path: Path | None = None) -> int:
    mapping = build_tag_dictionary(db_path)
    dest = path or _dict_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return len(mapping)


def _dict_source_mtime() -> float:
    """各词典源文件最新修改时间，用于按需 reload。"""
    latest = 0.0
    for path in (
        _dict_path(),
        _danbooru_rec_path(),
        _danbooru_ark_path(),
        _char_presets_path(),
    ):
        try:
            if path.exists():
                latest = max(latest, path.stat().st_mtime)
        except OSError:
            pass
    return latest


def _load_ark_preset_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    preset_path = _char_presets_path()
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
                        if low.endswith("_(arknights)"):
                            labels[low] = name
        except Exception:
            pass
    return labels


class TagTranslator:
    def __init__(self, dict_path: Path | None = None):
        self.dict_path = dict_path or _dict_path()
        self._source_mtime = 0.0
        self._mapping = dict(STATIC_JP_ZH)
        self._mapping.update(_load_dict_file())
        self._mapping.update(_load_ark_preset_labels())
        self._danbooru_known, self._danbooru_appearance = _load_danbooru_sets()
        self._source_mtime = _dict_source_mtime()

    def reload(self) -> int:
        global _DANBOORU_KNOWN, _DANBOORU_APPEARANCE
        self._mapping = dict(STATIC_JP_ZH)
        self._mapping.update(_load_dict_file())
        self._mapping.update(_load_ark_preset_labels())
        self._danbooru_known, self._danbooru_appearance = _load_danbooru_sets()
        _DANBOORU_KNOWN, _DANBOORU_APPEARANCE = self._danbooru_known, self._danbooru_appearance
        self._source_mtime = _dict_source_mtime()
        return len(self._mapping)

    def reload_if_stale(self) -> int:
        """仅当词典源文件变更时才重新加载。"""
        current = _dict_source_mtime()
        if current <= self._source_mtime and self._mapping:
            return len(self._mapping)
        return self.reload()

    @property
    def size(self) -> int:
        return len(self._mapping)

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._mapping)

    def translate(self, tag: str) -> dict:
        original = str(tag or "").strip()
        if not original:
            return {
                "original": "",
                "zh": "",
                "translated": False,
                "source": "empty",
            }

        if original in self._mapping:
            zh = self._mapping[original]
            return {
                "original": original,
                "zh": zh,
                "translated": zh != original,
                "source": "dict",
            }

        m = _ARKNIGHTS_SUFFIX.match(original)
        if m:
            inner = m.group(1)
            if inner in self._mapping:
                zh = self._mapping[inner]
                return {
                    "original": original,
                    "zh": zh,
                    "translated": True,
                    "source": "arknights_suffix",
                }

        m2 = _PAREN_SUFFIX.match(original)
        if m2:
            inner = m2.group(1)
            if inner in self._mapping:
                zh = self._mapping[inner]
                return {
                    "original": original,
                    "zh": zh,
                    "translated": True,
                    "source": "paren_strip",
                }

        if _CHINESE.search(original) and not _is_mostly_japanese(original):
            return {
                "original": original,
                "zh": original,
                "translated": False,
                "source": "already_zh",
            }

        low = original.lower()
        if low.endswith("_(arknights)"):
            inner = low[: -len("_(arknights)")]
            for candidate in (f"{inner}(アークナイツ)", f"{inner.replace('_', '')}(アークナイツ)"):
                if candidate in self._mapping:
                    zh = self._mapping[candidate]
                    return {
                        "original": original,
                        "zh": zh,
                        "translated": True,
                        "source": "arknights_romaji",
                        "danbooru": True,
                    }

        if low in self._danbooru_known or low in self._danbooru_appearance:
            if low in self._mapping and self._mapping[low] != low:
                zh = self._mapping[low]
            else:
                zh = _humanize_danbooru_tag(low)
            return {
                "original": original,
                "zh": zh,
                "translated": zh.lower() != low,
                "source": "danbooru",
                "danbooru": True,
            }

        if "_" in low and not _HIRAGANA_KATAKANA.search(original):
            zh = _humanize_danbooru_tag(low)
            if zh and zh.lower() != low:
                return {
                    "original": original,
                    "zh": zh,
                    "translated": True,
                    "source": "danbooru_humanize",
                    "danbooru": False,
                }

        if not _HIRAGANA_KATAKANA.search(original):
            return {
                "original": original,
                "zh": original,
                "translated": False,
                "source": "latin",
            }

        return {
            "original": original,
            "zh": original,
            "translated": False,
            "source": "fallback",
        }

    def translate_many(self, tags: list[str]) -> list[dict]:
        return [self.translate(tag) for tag in tags]


def main() -> None:
    count = save_tag_dictionary()
    translator = TagTranslator()
    samples = [
        "アーミヤ(アークナイツ)",
        "スカジ(アークナイツ)",
        "女の子",
        "明日方舟",
        "阿米娅",
        "極上の女体",
    ]
    print(f"saved {count} mappings -> {_dict_path()}")
    for tag in samples:
        print(tag, "->", translator.translate(tag))


if __name__ == "__main__":
    main()
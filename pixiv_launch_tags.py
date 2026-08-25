"""投稿标签工具：双语提示、标签平衡、Prompt/PNG 标签提取（从 pixiv_launch.py 拆出）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from nai_char import prompt_snapshot_from_comment, prompt_snapshot_from_png
from pixiv_char_tags import collect_ark_char_pixiv_hints
from pixiv_launch_config import DATA_DIR, GENERATED_DIR, PIXIV_MAX_TAGS


def _local_persona(direction: str, nickname_hint: str = "") -> dict[str, Any]:
    nick = nickname_hint.strip() or "星野画布"
    return {
        "account_name_suggestion": nick,
        "persona_summary": f"偏{direction}的 AI 发图爱好者账号，用 NovelAI 等工具摸鱼出图。",
        "bio_template": f"AI 辅助创作 | {direction} | 感谢喜欢",
        "voice_tone": "像真实爱好者，真诚克制，不装职业画师",
        "content_pillars": [
            "单张角色立绘与氛围图",
            "固定画风串与角色偏好",
            "简介里带一点画面感",
        ],
        "posting_rhythm": "每周 2-3 更，稳定更新比爆更更重要",
        "tag_strategy": ["AI绘画", "二次元", "插画", "AIイラスト", "イラスト", "オリジナル"],
        "hashtag_style": "中文为主，辅以少量日文检索 tag",
        "sample_greetings": ["今天也画了喜欢的角色。", "慢慢摸了一张，希望你会喜欢。"],
        "source": "local_fallback",
    }


def _load_tag_lexicon() -> dict[str, Any]:
    path = DATA_DIR / "pixiv_general_jp.json"
    if not path.exists():
        return {"mappings": {}, "force_original": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"mappings": {}}
    except Exception:
        return {"mappings": {}}


def _mapping_zh_ja(entry: Any) -> tuple[str, str]:
    if isinstance(entry, dict):
        return (
            str(entry.get("zh") or "").strip(),
            str(entry.get("ja") or "").strip(),
        )
    if isinstance(entry, str):
        return "", entry.strip()
    return "", ""


def _looks_chinese_tag(tag: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(tag or "")))


def _looks_japanese_tag(tag: str) -> bool:
    text = str(tag or "").strip()
    if not text:
        return False
    if _looks_chinese_tag(text) and not re.search(r"[\u3040-\u30ff]", text):
        return False
    if re.search(r"[\u3040-\u30ff]", text):
        return True
    return text in {
        "AI",
        "R-18",
        "R18",
        "SFW",
        "NSFW",
        "AIイラスト",
        "イラスト",
        "オリジナル",
        "女の子",
        "男の子",
        "アークナイツ",
        "原神",
        "崩壊スターレイル",
        "ブルーアーカイブ",
    }


def _collect_bilingual_hints(
    prompt_text: str,
    source_tags: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    lex = _load_tag_lexicon()
    mappings = lex.get("mappings") or {}
    character_zh = lex.get("character_zh") or {}
    series_zh = lex.get("series_zh") or {}
    series_ja = lex.get("series_ja") or {}
    zh_hints: list[str] = []
    ja_hints: list[str] = []
    zh_seen: set[str] = set()
    ja_seen: set[str] = set()

    def _add_zh(tag: str) -> None:
        if tag and tag not in zh_seen:
            zh_seen.add(tag)
            zh_hints.append(tag)

    def _add_ja(tag: str) -> None:
        if tag and tag not in ja_seen:
            ja_seen.add(tag)
            ja_hints.append(tag)

    tokens: list[str] = []
    for pool in (source_tags or [], re.split(r"[,，|]+", str(prompt_text or ""))):
        for raw in pool:
            tag = _normalize_tag_token(str(raw))
            if tag and len(tag) >= 2 and tag not in tokens:
                tokens.append(tag)

    for tag in tokens:
        low = tag.lower()
        zh, ja = _mapping_zh_ja(mappings.get(low) or mappings.get(tag))
        if zh:
            _add_zh(zh)
        if ja:
            _add_ja(ja)

        char_zh = character_zh.get(low)
        if char_zh:
            _add_zh(str(char_zh))

        match = re.match(r"^(.+)_\(([^)]+)\)$", low)
        if match:
            series_key = match.group(2).strip()
            if series_key in series_zh:
                _add_zh(str(series_zh[series_key]))
            if series_key in series_ja:
                _add_ja(str(series_ja[series_key]))
            whole = character_zh.get(low)
            if whole:
                _add_zh(str(whole))

    ark_zh, ark_ja = collect_ark_char_pixiv_hints(tokens)
    for tag in reversed(ark_ja):
        if tag and tag not in ja_seen:
            ja_seen.add(tag)
            ja_hints.insert(0, tag)
    for tag in reversed(ark_zh):
        if tag and tag not in zh_seen:
            zh_seen.add(tag)
            zh_hints.insert(0, tag)

    for tag in lex.get("zh_core") or []:
        _add_zh(str(tag).strip())
    for tag in lex.get("ja_core") or []:
        _add_ja(str(tag).strip())

    if lex.get("force_original"):
        _add_zh("同人")
        _add_ja("オリジナル")

    return zh_hints[:10], ja_hints[:8]


def _tag_hints_from_prompt(
    prompt_text: str,
    source_tags: list[str] | None = None,
) -> list[str]:
    zh_hints, ja_hints = _collect_bilingual_hints(prompt_text, source_tags)
    return _balance_upload_tags([], zh_hints, ja_hints, [])


def _balance_upload_tags(
    tags: list[str],
    zh_hints: list[str] | None = None,
    ja_hints: list[str] | None = None,
    defaults: list[str] | None = None,
    *,
    max_tags: int = PIXIV_MAX_TAGS,
    min_zh: int = 5,
    min_ja: int = 2,
    max_ja: int = 4,
) -> list[str]:
    zh_pool = list(zh_hints or [])
    ja_pool = list(ja_hints or [])
    for tag in defaults or []:
        text = str(tag).strip()
        if not text:
            continue
        if _looks_japanese_tag(text):
            ja_pool.append(text)
        else:
            zh_pool.append(text)

    out: list[str] = []
    seen: set[str] = set()

    def _push(tag: str) -> None:
        text = str(tag).strip()
        if not text or text in seen:
            return
        seen.add(text)
        out.append(text)

    for tag in tags or []:
        _push(tag)

    zh_count = sum(1 for t in out if _looks_chinese_tag(t) and not _looks_japanese_tag(t))
    ja_count = sum(1 for t in out if _looks_japanese_tag(t))

    for tag in zh_pool:
        if len(out) >= max_tags:
            break
        if zh_count >= min_zh and ja_count < min_ja:
            break
        before = len(out)
        _push(tag)
        if len(out) > before and _looks_chinese_tag(tag):
            zh_count += 1

    for tag in ja_pool:
        if len(out) >= max_tags or ja_count >= max_ja:
            break
        before = len(out)
        _push(tag)
        if len(out) > before and _looks_japanese_tag(tag):
            ja_count += 1

    for tag in zh_pool:
        if len(out) >= max_tags or zh_count >= min_zh:
            break
        before = len(out)
        _push(tag)
        if len(out) > before and _looks_chinese_tag(tag):
            zh_count += 1

    for tag in ja_pool:
        if len(out) >= max_tags or ja_count >= min_ja:
            break
        before = len(out)
        _push(tag)
        if len(out) > before and _looks_japanese_tag(tag):
            ja_count += 1

    return out[:max_tags]


def _split_tags(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[,，\n|]+", str(text or "")):
        tag = raw.strip().strip("{}")
        if tag and tag not in out:
            out.append(tag)
    return out


_TAG_NOISE = {
    "best quality",
    "absurdres",
    "masterpiece",
    "very aesthetic",
    "no text",
    "year 2025",
    "highres",
    "newest",
    "novelai",
    "description",
    "comment",
    "title",
    "software",
    "source",
}


def _normalize_tag_token(raw: str) -> str:
    tag = str(raw or "").strip().strip("{}").strip()
    tag = re.sub(r"^-?\d+(?:\.\d+)?::", "", tag)
    tag = re.sub(r"::$", "", tag)
    return tag.strip()


def _is_pipeline_noise_tag(tag: str) -> bool:
    low = str(tag or "").strip().lower()
    if not low or low in _TAG_NOISE:
        return True
    if low.startswith("cleaned_at=") or low.startswith("aitag-"):
        return True
    return False


def _tags_from_caption_text(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"[,，\n|]+", str(text or "")):
        tag = _normalize_tag_token(raw)
        if not tag or len(tag) < 2:
            continue
        low = tag.lower()
        if low in _TAG_NOISE:
            continue
        if tag not in out:
            out.append(tag)
    return out


def _prompt_text_from_snapshot(snapshot: dict[str, Any] | None) -> str:
    if not isinstance(snapshot, dict):
        return ""
    parts: list[str] = []
    base = str(snapshot.get("base_caption") or "").strip()
    if base:
        parts.append(base)
    for ch in snapshot.get("char_captions") or []:
        if not isinstance(ch, dict):
            continue
        cap = str(ch.get("caption") or "").strip()
        if cap:
            parts.append(cap)
    return " | ".join(parts)[:2000]


def _tags_from_prompt_snapshot(snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    combined = _prompt_text_from_snapshot(snapshot)
    return _tags_from_caption_text(combined.replace("::", ","))[:80]


def _tags_from_pipeline_meta_cfg(meta_cfg: dict[str, Any] | None) -> list[str]:
    meta_cfg = meta_cfg if isinstance(meta_cfg, dict) else {}
    out: list[str] = []
    png_text = meta_cfg.get("png_text") or {}
    if isinstance(png_text, dict):
        for key in ("Description", "description", "tags", "Tags", "prompt", "Prompt"):
            if key in png_text:
                for t in _split_tags(str(png_text.get(key) or "")):
                    if t not in out:
                        out.append(t)
    note = str(meta_cfg.get("custom_note") or "").strip()
    if note:
        for t in _split_tags(note):
            if t not in out:
                out.append(t)
    return out


def _read_png_text_tags(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        from PIL import Image

        with Image.open(path) as img:
            text = img.text or {}
        out: list[str] = []
        for key in ("Description", "description", "prompt", "Prompt", "tags", "Tags"):
            if key in text:
                for t in _split_tags(str(text.get(key) or "")):
                    if t not in out and not _is_pipeline_noise_tag(t):
                        out.append(t)
        if not out:
            for value in text.values():
                for t in _split_tags(str(value or "")):
                    if t not in out and not _is_pipeline_noise_tag(t):
                        out.append(t)
        return out[:40]
    except Exception:
        return []


def _resolve_prompt_snapshot(meta: dict[str, Any], stem: str) -> dict[str, Any] | None:
    snapshot = meta.get("prompt_snapshot")
    if isinstance(snapshot, dict) and (
        snapshot.get("base_caption") or snapshot.get("char_captions")
    ):
        return snapshot
    patched = meta.get("patched_comment")
    if isinstance(patched, dict) and patched:
        snap = prompt_snapshot_from_comment(patched)
        if snap.get("base_caption") or snap.get("char_captions"):
            return snap
    from generated_layout import resolve_png

    source = resolve_png(f"{stem}.png", root=GENERATED_DIR)
    return prompt_snapshot_from_png(source)

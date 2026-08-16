"""Shared helpers for multi-gallery asset importers (NAI only)."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gallery_catalog import ensure_gallery_dirs, get_db  # noqa: E402

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def stable_work_id(*parts: str) -> int:
    raw = "||".join(str(p) for p in parts)
    digest = hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()
    # 52-bit positive integer: JSON/JavaScript can represent it exactly.
    return int(digest[:13], 16) or 1


def account_user_id(account_key: str) -> int:
    return stable_work_id("account", account_key) % 2_000_000_000 or 1


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "").strip())
    text = re.sub(r"\s+", "_", text)
    return (text or "item")[:max_len]


def _load_cjk_font(size: int):
    from PIL import ImageFont

    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        "msyh.ttc",
        "arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_mixed(text: str, *, max_chars: int = 16, max_lines: int = 8) -> list[str]:
    """Wrap CJK + latin without breaking mid-word for ASCII tokens."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if not s:
        return ["(empty)"]
    lines: list[str] = []
    buf = ""
    width = 0

    def char_w(ch: str) -> int:
        # CJK roughly double width
        o = ord(ch)
        if ch == " ":
            return 1
        if o < 128:
            return 1
        return 2

    i = 0
    while i < len(s) and len(lines) < max_lines:
        ch = s[i]
        # keep ascii words together when possible
        if "A" <= ch <= "z" or ch.isdigit():
            j = i
            while j < len(s) and (("A" <= s[j] <= "z") or s[j].isdigit() or s[j] in "._-"):
                j += 1
            token = s[i:j]
            tw = sum(char_w(c) for c in token)
            if width + tw > max_chars and buf:
                lines.append(buf)
                buf = token
                width = tw
            else:
                buf += token
                width += tw
            i = j
            continue
        cw = char_w(ch)
        if width + cw > max_chars and buf:
            lines.append(buf)
            buf = ch
            width = cw
        else:
            buf += ch
            width += cw
        i += 1
    if buf and len(lines) < max_lines:
        lines.append(buf)
    if len(s) > 0 and len(lines) >= max_lines and i < len(s):
        lines[-1] = lines[-1][:-1] + "…"
    return lines or ["(empty)"]


def write_preview_card(
    dest: Path,
    *,
    title: str,
    subtitle: str = "",
    footer: str = "NAI",
    accent: tuple[int, int, int] = (76, 159, 255),
    badge: str = "",
    category: str = "",
) -> None:
    """Generate a readable local preview card for prompt-only codex assets."""
    from PIL import Image, ImageDraw, ImageFilter

    dest.parent.mkdir(parents=True, exist_ok=True)
    w, h = 576, 768
    # gradient-ish background
    base = (16, 20, 32)
    img = Image.new("RGB", (w, h), base)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(base[0] + (accent[0] - base[0]) * 0.08 * t)
        g = int(base[1] + (accent[1] - base[1]) * 0.08 * t)
        b = int(base[2] + (accent[2] - base[2]) * 0.10 * t)
        draw.line((0, y, w, y), fill=(r, g, b))

    # top accent bar + soft glow band
    draw.rectangle((0, 0, w, 10), fill=accent)
    draw.rectangle((24, 28, w - 24, 120), fill=(24, 30, 44))
    draw.rounded_rectangle((24, 140, w - 24, h - 72), radius=18, fill=(22, 28, 42))

    font_badge = _load_cjk_font(20)
    font_title = _load_cjk_font(34)
    font_body = _load_cjk_font(22)
    font_small = _load_cjk_font(18)

    badge_text = (badge or category or "CODEX").strip()
    if badge_text:
        bw = min(w - 60, 12 + sum(12 if ord(c) < 128 else 20 for c in badge_text[:18]))
        draw.rounded_rectangle((36, 44, 36 + bw, 84), radius=12, fill=accent)
        draw.text((48, 50), badge_text[:18], fill=(12, 16, 24), font=font_badge)

    y = 160
    for line in _wrap_mixed(title, max_chars=18, max_lines=3):
        draw.text((48, y), line, fill=(245, 248, 255), font=font_title)
        y += 44
    y += 8
    draw.line((48, y, w - 48, y), fill=(accent[0], accent[1], accent[2], 80)[:3])
    y += 16

    body = subtitle or ""
    for line in _wrap_mixed(body, max_chars=28, max_lines=10):
        draw.text((48, y), line, fill=(176, 192, 214), font=font_body)
        y += 30
        if y > h - 120:
            break

    draw.rectangle((0, h - 56, w, h), fill=(12, 16, 26))
    draw.text((28, h - 40), str(footer)[:48], fill=accent, font=font_small)
    # slight sharpen via re-encode quality
    img = img.filter(ImageFilter.SMOOTH_MORE)
    img.save(dest, format="WEBP", quality=90, method=6)


def upsert_local_work(
    gallery_id: str,
    *,
    work_id: int,
    title: str,
    caption: str = "",
    tags: str = "",
    prompt_text: str = "",
    model: str = "",
    ai_json: str = "",
    preview_rel: str,
    account_key: str = "",
    account_label: str = "",
    category: str = "",
    rating: str = "",
    source: str = "",
    extra: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    from library_writer import MaterializePage, materialize_asset
    from remote_asset import RemoteAssetRef

    ensure_gallery_dirs(gallery_id)
    db = get_db(gallery_id)
    crawled_at = now_iso()
    remote = None
    extra_payload = dict(extra or {})
    raw_remote = extra_payload.pop("remote_ref", None)
    if isinstance(raw_remote, RemoteAssetRef):
        remote = raw_remote
    elif isinstance(raw_remote, dict):
        remote = RemoteAssetRef.from_dict(raw_remote)
    elif source.startswith("local-drop:"):
        remote = RemoteAssetRef(
            provider_id="local-drop",
            remote_id=str(work_id),
            source_key=str(source),
        )
    elif source.startswith("qq") or gallery_id == "qqgroup":
        remote = RemoteAssetRef.for_qq(str(work_id), path=str(source or preview_rel))
    elif gallery_id == "codex":
        remote = RemoteAssetRef.for_codex(str(work_id), source_key=str(source or preview_rel))
    source_sha256 = str(extra_payload.pop("source_sha256", "") or "")
    materialize_asset(
        gallery_id,
        work_id=work_id,
        title=title,
        remote_ref=remote,
        pages=[
            MaterializePage(
                relative_path=preview_rel,
                page_index=0,
                source_sha256=source_sha256,
                file_name=Path(preview_rel).name,
                prompt_text=prompt_text,
                model=model,
                ai_json=ai_json,
            )
        ],
        caption=caption,
        tags=tags,
        account_key=account_key,
        account_label=account_label,
        category=category,
        rating=rating,
        source=source,
        extra=extra_payload or None,
        commit=commit,
        db=db,
        acquired_at=crawled_at,
    )


def save_group_index(gallery_id: str, groups: list[dict[str, Any]]) -> None:
    db = get_db(gallery_id)
    db.set_state(f"group_index:{gallery_id}", json.dumps(groups, ensure_ascii=False))

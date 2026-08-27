#!/usr/bin/env python3
"""Build the complete phone character index from the desktop char_tag_index pack."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INDEX = DATA / "char_tag_index.json"
OUT_CHARS = DATA / "phone_char_index.txt"
OUT_COPYRIGHTS = DATA / "phone_copyright_index.txt"


def _clean(raw: object) -> str:
    tag = str(raw or "").strip().lower()
    if not tag or len(tag) > 96:
        return ""
    return tag


def main() -> None:
    pack = json.loads(INDEX.read_text(encoding="utf-8"))
    seen: set[str] = set()
    chars: list[str] = []
    for raw in pack.get("characters") or []:
        tag = _clean(raw)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        chars.append(tag)
    copyrights: list[str] = []
    seen_c: set[str] = set()
    for raw in pack.get("copyrights") or []:
        tag = _clean(raw)
        if not tag or tag in seen_c:
            continue
        seen_c.add(tag)
        copyrights.append(tag)
    OUT_CHARS.write_text("\n".join(chars) + "\n", encoding="utf-8")
    OUT_COPYRIGHTS.write_text("\n".join(copyrights) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT_CHARS} lines={len(chars)} bytes={OUT_CHARS.stat().st_size} "
        f"copyrights={len(copyrights)} pack={INDEX.stat().st_size}"
    )


if __name__ == "__main__":
    main()

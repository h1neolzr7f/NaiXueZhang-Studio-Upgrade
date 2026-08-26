#!/usr/bin/env python3
"""Build the compact Danbooru character index used by the phone app."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "phone_char_index.txt"
REC = DATA / "danbooru_recognition.json"
PAT = re.compile(r"^[a-z0-9][a-z0-9_'.\-]*_\([^)]+\)$", re.I)
SKIP = re.compile(r"(cosplay|crossover|parody|meme|logo|symbol|chibi_version)", re.I)


def main() -> None:
    rec = json.loads(REC.read_text(encoding="utf-8"))
    seen: set[str] = set()
    tags: list[str] = []
    for raw in rec.get("characters") or []:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().lower()
        if tag in seen or len(tag) > 72 or not PAT.match(tag) or SKIP.search(tag):
            continue
        seen.add(tag)
        tags.append(tag)
    OUT.write_text("\n".join(tags) + "\n", encoding="utf-8")
    print(f"wrote {OUT} lines={len(tags)} bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()

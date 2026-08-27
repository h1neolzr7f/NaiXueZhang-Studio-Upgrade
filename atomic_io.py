"""Small atomic-file primitives for local desktop configuration."""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{secrets.token_hex(6)}.tmp")
    try:
        temporary.write_bytes(payload)
        last_error: PermissionError | None = None
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                return
            except PermissionError as error:
                # Windows 杀软/索引器或刚读完的句柄会短暂占着目标文件。
                last_error = error
                time.sleep(0.02 * (attempt + 1))
        try:
            path.write_bytes(payload)
        except PermissionError:
            if last_error is not None:
                raise last_error
            raise
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """JSON 落盘 + 原子替换；Windows 杀软/索引器短暂占用时退化为直接重写。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    try:
        temporary.replace(path)
    except PermissionError:
        path.write_text(text, encoding="utf-8")
        temporary.unlink(missing_ok=True)

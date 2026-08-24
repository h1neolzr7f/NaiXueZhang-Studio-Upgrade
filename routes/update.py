"""Update checker and downloader for the standalone EXE distribution.

The update source is configured via ``update_url`` in config.json. It must be
an HTTPS endpoint serving ``version.json`` in the shape
``{"version": "x.y.z", "url": "https://...", "sha256": "..."}``.
Downloads are written to a temporary file, verified, and atomically promoted.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import string
import json
import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

from server_shared import CONFIG, DATA_DIR, ROOT


router = APIRouter(prefix="/api/update", tags=["update"])
_HEX = frozenset(string.hexdigits)


def _current_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _update_dir() -> Path:
    if getattr(sys, "frozen", False):
        return ROOT / "update"
    return DATA_DIR / "update"


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in _HEX for character in value)


def _fetch_manifest(client: httpx.Client) -> dict:
    base = str(CONFIG.get("update_url") or "").strip().rstrip("/")
    if not base:
        raise HTTPException(status_code=400, detail="更新源未配置（config update_url）")
    if not base.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="更新清单仅支持 HTTPS 来源")
    try:
        response = client.get(f"{base}/version.json", timeout=20)
        response.raise_for_status()
        manifest = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"更新源不可用：{exc}") from exc
    if not isinstance(manifest, dict) or not manifest.get("version"):
        raise HTTPException(status_code=502, detail="更新源返回了无效的 version.json")
    return manifest


@router.get("/check")
def api_update_check() -> dict:
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        manifest = _fetch_manifest(client)
    current = _current_version()
    remote = str(manifest["version"]).strip()
    return {
        "ok": True,
        "current_version": current,
        "latest_version": remote,
        "update_available": remote != current,
        "url": str(manifest.get("url") or ""),
        "sha256": str(manifest.get("sha256") or ""),
    }


@router.post("/download")
def api_update_download() -> dict:
    with httpx.Client(timeout=600, follow_redirects=True) as client:
        try:
            manifest = _fetch_manifest(client)
            url = str(manifest.get("url") or "").strip()
            expected_sha = str(manifest.get("sha256") or "").strip().lower()
            if not url:
                raise HTTPException(status_code=502, detail="更新源未提供下载 URL")
            if not url.lower().startswith("https://"):
                raise HTTPException(status_code=502, detail="更新包仅支持 HTTPS 下载")
            if not _valid_sha256(expected_sha):
                raise HTTPException(
                    status_code=502,
                    detail="更新清单缺少有效的 SHA-256，拒绝下载（供应链防护）",
                )
            target_dir = _update_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / "update.exe"
            temporary = target_dir / f"update.{secrets.token_hex(6)}.tmp"
            digest = hashlib.sha256()
            try:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                            digest.update(chunk)
                            handle.write(chunk)
                actual = digest.hexdigest()
                if actual != expected_sha:
                    raise HTTPException(status_code=502, detail="下载校验失败：SHA-256 不匹配")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"下载失败：{exc}") from exc
    return {
        "ok": True,
        "downloaded": True,
        "filename": target.name,
        "sha256": actual,
        "message": "更新包已下载，重启应用后将自动完成安装。",
    }

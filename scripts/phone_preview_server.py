#!/usr/bin/env python3
"""Local preview of the standalone phone UI without an Android device."""

from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATA = ROOT / "data"
PORT = 18797

DEMO_ID = "demo-ark-amiya"


def _png(index: int) -> bytes:
    # 1x1 PNG, valid enough for <img>. The Android app draws a real card.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d4944415478da63f8cfc0f00f0005fe01fe6c7d9a2e0000000049454e44ae426082"
    )


def _demo_work() -> dict:
    slot0 = "amiya_(arknights), 1girl, brown_hair, blue_eyes, rabbit_ears, standing"
    slot1 = "kaltsit_(arknights), 1girl, white_hair, green_eyes, labcoat"
    page0 = {
        "image_id": f"{DEMO_ID}_p0",
        "id": f"{DEMO_ID}_p0",
        "page_index": 0,
        "width": 832,
        "height": 1216,
        "model": "nai-diffusion-4-5-full",
        "prompt_text": "2girls, rhodes island infirmary, soft lighting, official art",
        "url": f"/api/mobile/demo/image/0",
        "thumbnail_url": f"/api/mobile/demo/image/0",
        "ai_json": {
            "Comment": {
                "prompt": "2girls, rhodes island infirmary, soft lighting, official art",
                "width": 832,
                "height": 1216,
                "steps": 28,
                "model": "nai-diffusion-4-5-full",
                "negative_prompt": "lowres, bad anatomy, worst quality",
                "v4_prompt": {
                    "caption": {
                        "base_caption": "2girls, rhodes island infirmary, soft lighting, official art",
                        "char_captions": [
                            {"char_caption": slot0, "centers": [{"x": 0.32, "y": 0.5}]},
                            {"char_caption": slot1, "centers": [{"x": 0.68, "y": 0.5}]},
                        ],
                    }
                },
            }
        },
    }
    page1 = json.loads(json.dumps(page0))
    page1.update({
        "image_id": f"{DEMO_ID}_p1",
        "id": f"{DEMO_ID}_p1",
        "page_index": 1,
        "prompt_text": "1girl, moonlight rooftop, city lights",
        "url": "/api/mobile/demo/image/1",
        "thumbnail_url": "/api/mobile/demo/image/1",
    })
    page1["ai_json"]["Comment"]["prompt"] = page1["prompt_text"]
    page1["ai_json"]["Comment"]["v4_prompt"]["caption"]["base_caption"] = page1["prompt_text"]
    page1["ai_json"]["Comment"]["v4_prompt"]["caption"]["char_captions"] = [
        {"char_caption": "amiya_(arknights), 1girl, brown_hair, blue_eyes, looking_at_viewer, sitting", "centers": [{"x": 0.5, "y": 0.5}]}
    ]
    work = {
        "work_id": DEMO_ID,
        "id": DEMO_ID,
        "title": "内置样例 · 阿米娅换角",
        "creator": "phone-demo",
        "ai_type": "NovelAI",
        "image_count": 2,
        "tags": ["明日方舟", "阿米娅", "NovelAI"],
        "images": [page0, page1],
        "demo": True,
    }
    return {
        "ok": True,
        "work": work,
        "images": [page0, page1],
        "source": "phone-demo",
        "demo": True,
        "generation_calls": 0,
        "character_candidates": [],
    }


def _load_json(name: str) -> dict:
    path = DATA / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


ARK = _load_json("ark_char_library.json")
PRESETS = _load_json("char_presets.json")
STYLES = _load_json("phone_style_index.json")
SERIES = _load_json("phone_series_aliases.json")
ARK_ALIASES = _load_json("ark_cn_aliases.json")
CHAR_INDEX = (DATA / "phone_char_index.txt").read_text(encoding="utf-8").splitlines() if (DATA / "phone_char_index.txt").is_file() else []
COPYRIGHTS = set((DATA / "phone_copyright_index.txt").read_text(encoding="utf-8").splitlines()) if (DATA / "phone_copyright_index.txt").is_file() else set()
TAG_DICT = _load_json("tag_dict.json")
FAV_IDS: list[str] = [DEMO_ID]
OUTPUTS: list[dict] = []
ALBUMS: list[dict] = []
PIPELINE_CFG: dict = {
    "auto_after_generate": True,
    "upscale": True,
    "scale": 2,
    "metadata": True,
    "mosaic": True,
    "mosaic_available": True,
    "mosaic_mode": "light",
    "mosaic_method": "像素",
    "mosaic_intensity": 36,
    "estimate_ms": 2200,
}
JOB_SEQ = 1
JOBS: dict[str, dict] = {
    "preview-error": {
        "task_id": "preview-error",
        "album_id": "preview-error",
        "status": "error",
        "terminal": True,
        "cancellable": False,
        "retryable": True,
        "done": 0,
        "total": 4,
        "pages": 2,
        "progress": 12,
        "stage": "error",
        "stage_label": "失败",
        "eta_seconds": 0,
        "eta_text": "",
        "title": "香蕉姐 · 全系列",
        "message": "生成连接被掐断。没看到成功回执，先看 NovelAI 记录有没有扣费，再手动重试",
    },
    "preview-running": {
        "task_id": "preview-running",
        "album_id": "preview-running",
        "status": "running",
        "terminal": False,
        "cancellable": True,
        "retryable": False,
        "done": 1,
        "total": 4,
        "pages": 2,
        "copies": 2,
        "running": 1,
        "concurrency": 2,
        "progress": 38,
        "stage": "generating",
        "stage_label": "正在出图",
        "eta_seconds": 22,
        "eta_text": "预计还要 22 秒",
        "expected_seconds": 28,
        "title": "阿米娅 · 全系列",
        "message": "生成中 1/4 · 2 路并发",
        "_t0": time.time(),
    },
}
CUSTOM: list[dict] = []
CUSTOM_STYLES: list[dict] = []
PREVIEW_TOKENS: list[str] = []
_CHAR_PREFIX: dict[str, list[str]] | None = None
_CHAR_SERIES: dict[str, list[str]] | None = None
_SEARCH_CACHE: dict[str, list[str]] = {}
_HOT_SERIES = (
    "vocaloid", "genshin_impact", "arknights", "honkai:_star_rail", "honkai",
    "azur_lane", "blue_archive", "fate", "pokemon", "umamusume",
)


def _parse_tokens(raw: str) -> list[str]:
    text = str(raw or "").replace("\r", "\n").replace(",", "\n")
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        token = line.strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token or token.startswith("#"):
            continue
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _token_payload(message: str = "") -> dict:
    n = len(PREVIEW_TOKENS)
    shown = n if n else 1
    return {
        "ok": True,
        "has_token": True,
        "has_deepseek": True,
        "has_api_key": True,
        "token_count": shown,
        "enabled_count": shown,
        "concurrency": shown,
        "slots": shown,
        "message": message or ("已配置 " + str(shown) + " 个 Token，可 " + str(shown) + " 路并发"),
    }


def _format_eta(seconds: int) -> str:
    seconds = max(0, int(seconds))
    if seconds <= 0:
        return "即将完成"
    if seconds < 60:
        return "预计还要 " + str(seconds) + " 秒"
    minutes = seconds // 60
    rest = seconds % 60
    if rest == 0:
        return "预计还要 " + str(minutes) + " 分钟"
    return "预计还要 " + str(minutes) + " 分 " + str(rest) + " 秒"


def _estimate_seconds(total: int, concurrency: int) -> int:
    count = max(1, int(total or 1))
    slots = max(1, int(concurrency or 1))
    extra = 2.2
    if PIPELINE_CFG.get("upscale"):
        extra += 0.4 * int(PIPELINE_CFG.get("scale") or 2) ** 2
    if PIPELINE_CFG.get("mosaic"):
        extra += 1.1
    if PIPELINE_CFG.get("metadata", True):
        extra += 0.2
    waves = (count + slots - 1) // slots
    return max(4, int(round(waves * (12.0 + extra))))


def _decorate_job(job: dict) -> dict:
    out = dict(job)
    out.pop("_t0", None)
    status = str(out.get("status") or "")
    terminal = bool(out.get("terminal")) or status in {"done", "error", "cancelled", "unknown"}
    done = int(out.get("done") or 0)
    total = max(1, int(out.get("total") or 1))
    running = int(out.get("running") or 0)
    stage = str(out.get("stage") or status)
    if terminal and status == "done":
        out["progress"] = 100
        out["eta_seconds"] = 0
        out["eta_text"] = "已完成"
        out["stage_label"] = out.get("stage_label") or "完成"
        return out
    started = float(job.get("_t0") or 0)
    elapsed = max(0.0, time.time() - started) if started else 0.0
    if status == "queued":
        frac = 0.02
    else:
        unit = 0.55
        if stage in {"pipeline", "upscale", "mosaic"}:
            unit = 0.84
        elif stage == "saving":
            unit = 0.94
        elif stage == "requesting":
            unit = 0.16
        elif stage in {"generating", "running"}:
            unit = min(0.72, 0.18 + elapsed / 16.0)
        frac = done + running * unit
    progress = 100 if terminal and status == "done" else max(2, min(99, int(round(frac * 100 / total))))
    leftover = max(0, total - done)
    conc = max(1, int(out.get("concurrency") or 1))
    eta = 0 if terminal else max(1, _estimate_seconds(leftover, conc) - int(elapsed))
    out["progress"] = progress
    out["eta_seconds"] = 0 if terminal else eta
    out["eta_text"] = "" if terminal else _format_eta(eta)
    out["expected_seconds"] = out.get("expected_seconds") or _estimate_seconds(total, conc)
    if not out.get("stage_label"):
        labels = {
            "queued": "排队等待",
            "requesting": "正在请求 NovelAI",
            "generating": "正在出图",
            "running": "正在出图",
            "upscale": "本机超分",
            "mosaic": "轻量打码",
            "pipeline": "本机后处理",
            "saving": "写入图库",
        }
        out["stage_label"] = labels.get(stage, status or "生成中")
    return out


def _tick_jobs() -> None:
    now = time.time()
    job = JOBS.get("preview-running")
    if not job or job.get("terminal"):
        return
    started = float(job.setdefault("_t0", now))
    elapsed = now - started
    cycle = elapsed % 24.0
    if cycle < 6:
        job.update({"done": 1, "running": 1, "stage": "generating", "stage_label": "正在出图", "message": "生成中 1/4 · 2 路并发"})
    elif cycle < 10:
        job.update({"done": 2, "running": 1, "stage": "pipeline", "stage_label": "本机后处理：超分 2x，轻量打码 像素，清元数据开", "message": "生成中 2/4 · 轻量打码"})
    elif cycle < 16:
        job.update({"done": 3, "running": 1, "stage": "generating", "stage_label": "正在出图", "message": "生成中 3/4 · 2 路并发"})
    else:
        job.update({"done": 3, "running": 1, "stage": "saving", "stage_label": "写入图库和相册", "message": "生成中 3/4 · 写入图库"})


def _simulate_job(task_id: str, total: int, title: str) -> None:
    stages = (
        (0.4, "queued", "排队等待", 0, 0),
        (0.8, "requesting", "正在请求 NovelAI", 0, 1),
        (1.6, "generating", "正在出图", 0, 1),
        (0.6, "pipeline", "本机后处理：超分 / 轻量打码 / 清元数据", 0, 1),
        (0.4, "saving", "写入图库和相册", 1, 0),
    )
    job = JOBS.get(task_id)
    if not job:
        return
    finished = 0
    while finished < total and not job.get("terminal"):
        for wait, stage, label, add_done, running in stages:
            if job.get("terminal"):
                return
            job.update({
                "status": "running",
                "stage": stage,
                "stage_label": label,
                "running": running,
                "done": finished,
                "message": label + " · " + str(finished) + "/" + str(total),
            })
            time.sleep(wait)
            if add_done:
                finished += 1
                job["done"] = finished
                break
    if job.get("terminal"):
        return
    item = {
        "ok": True,
        "image_url": "/api/mobile/output/preview.png",
        "gallery_url": "/api/mobile/output/preview.png",
        "library_id": "g" + task_id,
        "album_id": task_id,
        "message": "完成：已入图库并跑完流水线（超分 + 轻量打码 + 清元数据）",
    }
    job.update({
        "status": "done",
        "terminal": True,
        "cancellable": False,
        "retryable": False,
        "done": total,
        "running": 0,
        "progress": 100,
        "stage": "done",
        "stage_label": "完成",
        "eta_seconds": 0,
        "eta_text": "已完成",
        "items": [item],
        "message": "完成 " + str(total) + " 张，已按同一任务收入图库",
    })


def _name_of(tag: str) -> str:
    raw = str(tag or "")
    if "_(" in raw and raw.endswith(")"):
        return raw.rsplit("_(", 1)[0]
    return raw


def _series_of(tag: str) -> str:
    raw = str(tag or "")
    if "_(" in raw and raw.endswith(")"):
        return raw.rsplit("_(", 1)[1][:-1]
    return ""


def _ensure_char_indexes() -> None:
    global _CHAR_PREFIX, _CHAR_SERIES
    if _CHAR_PREFIX is not None:
        return
    prefixes: dict[str, list[str]] = {}
    series: dict[str, list[str]] = {}
    for tag in CHAR_INDEX:
        name = _name_of(tag)
        if name:
            bucket = prefixes.setdefault(name[0], [])
            if len(bucket) < 400:
                bucket.append(tag)
        if len(name) >= 2:
            prefixes.setdefault(name[:2], []).append(tag)
        ser = _series_of(tag)
        if ser:
            series.setdefault(ser, []).append(tag)
    _CHAR_PREFIX, _CHAR_SERIES = prefixes, series


def _looks_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _resolve_alias(needle: str) -> str:
    if not needle:
        return ""
    direct = str(SERIES.get(needle) or SERIES.get(needle.lower()) or "").lower()
    if direct:
        return direct
    chinese = _looks_chinese(needle)
    best_key = ""
    best_val = ""
    for key, value in SERIES.items():
        lk = str(key).lower()
        if not lk:
            continue
        hit = lk in needle or ((chinese or len(needle) >= 2) and lk.startswith(needle)) or (chinese and needle in lk)
        if hit and len(lk) >= len(best_key):
            best_key = lk
            best_val = str(value).lower()
    return best_val


def _rank_tag(tag: str, compact: str, series: str) -> tuple:
    name = _name_of(tag)
    ser = _series_of(tag)
    junk = 10 if any(part in name for part in (
        "abyss", "slime", "hilichurl", "samachurl", "mitachurl", "spectator",
        "npc", "monster", "enemy", "cosplay",
    )) or "meme" in ser else 0
    hot = 0 if ser in _HOT_SERIES or any(ser.startswith(item) for item in _HOT_SERIES) else 1
    if compact and tag == compact:
        return (junk, 0, hot, len(name), tag)
    if compact and name == compact and hot == 0:
        return (1 + junk, 0, hot, len(name), tag)
    if compact and (name == compact or tag.startswith(compact + "_(")):
        return (2 + junk, 0, hot, len(name), tag)
    if compact and name.startswith(compact):
        return (3 + junk, 0, hot, len(name), tag)
    tokens = name.count("_")
    if series and tag.endswith("_(" + series + ")"):
        return (4 + junk + min(tokens, 3), 1, hot, len(name), tag)
    if series and series in tag:
        return (7 + junk, 1, hot, len(name), tag)
    return (8 + junk, 1, hot, len(name), tag)


def _human_tag(tag: str) -> str:
    raw = str(tag or "")
    if "_(" in raw and raw.endswith(")"):
        name, series = raw.rsplit("_(", 1)
        return f"{name.replace('_', ' ')} · {series[:-1].replace('_', ' ')}"
    return raw.replace("_", " ")


def _normalize_source(source: str) -> str:
    value = str(source or "").strip().lower()
    if value in {"", "all", "全部"}:
        return "all"
    if value in {"oc", "custom", "我的角色"}:
        return "oc"
    if value in {"ark", "arknights", "明日方舟", "明日方舟库"}:
        return "ark"
    if value in {"danbooru", "d", "d站"}:
        return "danbooru"
    return "all"


def _search_chars(gender: str, q: str, limit: int, source: str = "") -> list[dict]:
    needle = (q or "").strip().lower()
    compact = needle.replace(" ", "_")
    bucket = "male" if gender == "male" else "female"
    src = _normalize_source(source)
    alias = _resolve_alias(needle)
    series = alias if alias in COPYRIGHTS else ""
    if alias and not series:
        compact = alias
    items: list[dict] = []
    if src in {"all", "oc"}:
        for row in CUSTOM:
            if (row.get("gender") or bucket) not in {bucket, "", None}:
                continue
            blob = " ".join(str(row.get(k) or "") for k in ("id", "label", "name", "tag", "char_caption")).lower()
            if needle and needle not in blob:
                continue
            items.append({
                "reference_id": f"custom:{bucket}:{row.get('id')}",
                "label": row.get("label") or row.get("id"),
                "source": "OC",
                "record": dict(row, kind="oc"),
            })
    if src == "all":
        for row in PRESETS.get(bucket, []) or []:
            blob = " ".join(str(row.get(k) or "") for k in ("id", "label", "name", "tag")).lower()
            if needle and needle not in blob:
                continue
            items.append({"reference_id": f"preset:{bucket}:{row.get('id')}", "label": row.get("label") or row.get("id"), "source": "常用角色", "record": row})
    if src in {"all", "ark"}:
        for row in ARK.get(bucket, []) or []:
            tag = str(row.get("tag") or "")
            extra = " ".join(str(x) for x in (ARK_ALIASES.get(tag) or []))
            blob = " ".join(str(row.get(k) or "") for k in ("id", "label", "name", "tag")) + " " + extra
            blob = blob.lower()
            if needle and needle not in blob:
                continue
            items.append({"reference_id": f"ark:{bucket}:{row.get('id')}", "label": row.get("label") or row.get("id"), "source": "明日方舟库", "record": row})
            if len(items) >= limit:
                break
    if src in {"all", "danbooru"} and needle and len(items) < limit:
        cache_key = f"{bucket}|{compact}|{series}|{limit}"
        cached = _SEARCH_CACHE.get(cache_key)
        if cached is None:
            _ensure_char_indexes()
            pool: list[str] = []
            seen: set[str] = set()

            def add_all(rows: list[str] | None) -> None:
                for tag in rows or []:
                    if tag and tag not in seen:
                        seen.add(tag)
                        pool.append(tag)

            if series:
                add_all((_CHAR_SERIES or {}).get(series))
            if len(compact) >= 2:
                add_all((_CHAR_PREFIX or {}).get(compact[:2]))
            elif compact:
                add_all((_CHAR_PREFIX or {}).get(compact[:1]))
            if not pool and len(compact) >= 4:
                pool = list(CHAR_INDEX)
            cap = max(80, limit * 8)
            hits: list[str] = []
            for tag in pool:
                name = _name_of(tag)
                name_hit = bool(compact) and (
                    tag == compact
                    or tag.startswith(compact + "_(")
                    or name == compact
                    or name.startswith(compact)
                    or (len(compact) >= 3 and compact in name)
                )
                series_hit = bool(series) and (tag.endswith("_(" + series + ")") or series in tag)
                if name_hit or series_hit:
                    hits.append(tag)
                if len(hits) >= cap:
                    break
            hits.sort(key=lambda tag: _rank_tag(tag, compact, series))
            cached = hits[: max(0, limit - len(items))]
            _SEARCH_CACHE[cache_key] = list(cached)
            if len(_SEARCH_CACHE) > 64:
                _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))
        for tag in cached:
            record = {
                "id": tag,
                "label": _human_tag(tag),
                "gender": bucket,
                "tag": tag,
                "kind": "danbooru",
                "identity": ["1boy" if bucket == "male" else "1girl", tag],
            }
            items.append({"reference_id": f"danbooru:{bucket}:{tag}", "label": record["label"], "source": "D 站角色库", "record": record})
            if len(items) >= limit:
                break
    return items[:limit]


def _search_styles(q: str, limit: int) -> list[dict]:
    needle = (q or "").strip().lower()
    items = []
    for row in CUSTOM_STYLES + (STYLES.get("styles") or []):
        blob = " ".join(str(row.get(k) or "") for k in ("id", "label", "tag")).lower()
        if needle and needle not in blob:
            continue
        source = "我的画风" if row.get("source") == "phone-custom" else "内置画风"
        items.append({
            "reference_id": ("custom-style:" if row.get("source") == "phone-custom" else "style:") + str(row.get("id")),
            "label": row.get("label") or row.get("tag"),
            "source": source,
            "kind": "style",
            "record": row,
        })
        if len(items) >= limit:
            break
    return items


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = {key: values[0] if values else "" for key, values in parse_qs(parsed.query).items()}
        if path in {"/m", "/m/"}:
            html = (WEB / "m" / "index.html").read_text(encoding="utf-8")
            html = html.replace('data-mobile="1"', 'data-mobile="1" data-standalone="1"')
            html = html.replace("配对</button>", "设置</button>")
            inject = '<script>window.__NAI_STANDALONE__=true;window.__NAI_SESSION_TOKEN__="phone-local";</script>\n  '
            html = html.replace('<script src="/assets/m/standalone-core.js', inject + '<script src="/assets/m/standalone-core.js')
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path.startswith("/assets/m/"):
            name = path.split("/assets/m/", 1)[1].split("?", 1)[0]
            file = WEB / "m" / name
        elif path.startswith("/assets/shared/"):
            name = path.split("/assets/shared/", 1)[1].split("?", 1)[0]
            file = WEB / "shared" / name
        else:
            file = None
        if file and file.is_file():
            mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._send(200, file.read_bytes(), mime)
            return
        if path == "/api/mobile/status":
            payload = _token_payload()
            payload.update({"standalone": True, "loopback": True, "has_ai_key": True})
            return self._json(payload)
        if path == "/api/nai/status":
            return self._json(_token_payload())
        if path == "/api/ai/status":
            return self._json({"ok": True, "has_api_key": True, "has_deepseek": True})
        if path == "/api/nai/network":
            return self._json({"ok": True, "proxy": "", "online_use_proxy": True, "nai_use_proxy": False, "detected_proxy": ""})
        if path == "/api/nai/aitag/favorites":
            return self._json({"ok": True, "ids": FAV_IDS})
        if path in {"/api/nai/aitag/favorites/works", "/api/mobile/library/works"}:
            demo = _demo_work()["work"]
            demo["local"] = True
            demo["save_state"] = "ready"
            return self._json({"ok": True, "items": [demo], "works": [demo]})
        if path.startswith("/api/mobile/library/work/"):
            return self._json(_demo_work())
        if path == "/api/nai/aitag/search":
            work = _demo_work()["work"]
            locked = {
                "work_id": "online-locked-1",
                "id": "online-locked-1",
                "title": "在线待收藏 · 甘雨",
                "creator": "preview",
                "image_count": 1,
                "tags": ["原神", "甘雨"],
                "images": [{"url": "/api/mobile/demo/image/0", "thumbnail_url": "/api/mobile/demo/image/0"}],
                "local": False,
            }
            return self._json({
                "ok": True,
                "items": [work, locked],
                "works": [work, locked],
                "page": int(query.get("page") or 1),
                "has_more": False,
                "offline_demo": False,
                "source": "phone-demo",
            })
        if path.startswith("/api/nai/aitag/work/online-locked-1"):
            page = {
                "image_id": "online-locked-1_p0",
                "url": "/api/mobile/demo/image/0",
                "thumbnail_url": "/api/mobile/demo/image/0",
                "prompt_text": "1girl, ganyu_(genshin_impact), snow",
                "ai_json": {"Comment": {"prompt": "1girl, ganyu_(genshin_impact), snow"}},
            }
            return self._json({
                "ok": True,
                "work": {
                    "work_id": "online-locked-1",
                    "id": "online-locked-1",
                    "title": "在线待收藏 · 甘雨",
                    "creator": "preview",
                    "image_count": 1,
                    "tags": ["原神", "甘雨"],
                    "images": [page],
                },
                "images": [page],
                "generation_calls": 0,
            })
        if path.startswith("/api/nai/aitag/work/"):
            return self._json(_demo_work())
        if path.startswith("/api/nai/aitag/cover/") or path.startswith("/api/mobile/demo/image/"):
            return self._send(200, _png(0), "image/png")
        if path == "/api/plugin/char-swap/search":
            items = _search_chars(
                query.get("gender") or "female",
                query.get("q") or "",
                int(query.get("limit") or 24),
                query.get("source") or "",
            )
            return self._json({"ok": True, "items": items, "total": len(items), "source": query.get("source") or "all"})
        if path == "/api/plugin/char-swap/styles":
            items = _search_styles(query.get("q") or "", int(query.get("limit") or 40))
            return self._json({"ok": True, "items": items, "total": len(items)})
        if path == "/api/mobile/queue":
            _tick_jobs()
            items = [_decorate_job(job) for job in JOBS.values()]
            return self._json({"ok": True, "items": items, "total": len(items), "concurrency": max(1, len(PREVIEW_TOKENS) or 1)})
        if path == "/api/mobile/gallery":
            return self._json({"ok": True, "albums": ALBUMS, "items": ALBUMS, "total": len(ALBUMS), "grouped": True})
        if path.startswith("/api/mobile/gallery/"):
            album_id = unquote(path.split("/gallery/", 1)[1])
            album = next((item for item in ALBUMS if item.get("album_id") == album_id), None)
            if not album:
                return self._json({"ok": False, "detail": "图库里没有这个任务"}, 404)
            return self._json({"ok": True, "album": album, "images": album.get("images") or [], "grouped": True})
        if path == "/api/plugin/char-swap/ark-library":
            gender = "male" if query.get("gender") == "male" else "female"
            q = (query.get("q") or "").lower()
            items = []
            for row in ARK.get(gender, []) or []:
                blob = str(row.get("label") or "") + str(row.get("id") or "")
                if q and q not in blob.lower():
                    continue
                items.append(row)
                if len(items) >= 20:
                    break
            return self._json({"ok": True, "items": items})
        if path == "/api/plugin/char-swap/custom":
            return self._json({"ok": True, "items": CUSTOM})
        if path == "/api/mobile/outputs":
            return self._json({"ok": True, "albums": ALBUMS, "items": ALBUMS, "total": len(ALBUMS), "grouped": True})
        if path == "/api/pipeline/config":
            return self._json({
                "ok": True,
                "config": dict(PIPELINE_CFG),
                "message": "手机流水线：超分 + 轻量打码 + 清元数据。打码是肤色区域像素/模糊，不是电脑 ANR/YOLO。",
            })
        if path == "/api/pipeline/status":
            return self._json({"ok": True, "job": {"status": "idle"}, "backlog": {"count": 0}})
        if path.startswith("/api/nai/jobs"):
            _tick_jobs()
            task = query.get("task_id") or ""
            job = JOBS.get(task)
            if not job:
                return self._json({"ok": False, "detail": "generation task not found"}, 404)
            return self._json(_decorate_job(job))
        if path.startswith("/api/mobile/output/"):
            return self._send(200, _png(0), "image/png")
        if path == "/api/session-token":
            return self._json({"ok": True, "token": "phone-local"})
        self._json({"ok": False, "detail": "not found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        payload = self._read_json()
        if path.startswith("/api/nai/aitag/favorites/") and path.endswith("/toggle"):
            work_id = unquote(path.split("/favorites/", 1)[1].rsplit("/toggle", 1)[0])
            if work_id in FAV_IDS:
                FAV_IDS.remove(work_id)
                return self._json({"ok": True, "favorited": False, "message": "已取消收藏"})
            FAV_IDS.append(work_id)
            return self._json({"ok": True, "favorited": True, "remix_ready": True, "save_state": "ready", "message": "已入库。咒语已齐，可以换角。原图下不下都行。"})
        if path == "/api/plugin/char-swap/custom":
            item = dict(payload)
            item.setdefault("id", "c" + str(len(CUSTOM) + 1))
            item["kind"] = "oc"
            item["oc_mode"] = bool(item.get("oc_mode", bool(str(item.get("char_caption") or "").strip())))
            CUSTOM.insert(0, item)
            return self._json({"ok": True, "item": item, "message": "已保存 OC"})
        if path == "/api/plugin/char-swap/custom/delete":
            want = str(payload.get("id") or "")
            CUSTOM[:] = [item for item in CUSTOM if str(item.get("id")) != want]
            return self._json({"ok": True, "message": "已删除"})
        if path.startswith("/api/mobile/queue/") and path.endswith("/cancel"):
            task_id = unquote(path.split("/queue/", 1)[1].rsplit("/cancel", 1)[0])
            job = JOBS.get(task_id)
            if not job:
                return self._json({"ok": False, "detail": "队列里没有这个任务"}, 400)
            job["status"] = "cancelled"
            job["terminal"] = True
            job["cancellable"] = False
            job["retryable"] = True
            job["message"] = "已取消，未发出的张不会再生成"
            return self._json({**job, "ok": True, "message": job["message"]})
        if path.startswith("/api/mobile/queue/") and path.endswith("/retry"):
            task_id = unquote(path.split("/queue/", 1)[1].rsplit("/retry", 1)[0])
            job = JOBS.get(task_id)
            if not job:
                return self._json({"ok": False, "detail": "没有可重试的任务"}, 400)
            job["status"] = "queued"
            job["terminal"] = False
            job["cancellable"] = True
            job["retryable"] = False
            job["message"] = "已重新入队"
            return self._json({**job, "ok": True, "task_id": task_id, "album_id": job.get("album_id") or task_id, "message": "已重新入队"})
        if path.startswith("/api/mobile/queue/") and path.endswith("/delete"):
            task_id = unquote(path.split("/queue/", 1)[1].rsplit("/delete", 1)[0])
            if task_id not in JOBS:
                return self._json({"ok": False, "detail": "队列里没有这个任务"}, 400)
            JOBS.pop(task_id, None)
            return self._json({"ok": True, "task_id": task_id, "message": "已从队列删除"})
        if path.startswith("/api/mobile/gallery/") and path.endswith("/delete"):
            album_id = unquote(path.split("/gallery/", 1)[1].rsplit("/delete", 1)[0])
            before = len(ALBUMS)
            ALBUMS[:] = [item for item in ALBUMS if item.get("album_id") != album_id]
            if len(ALBUMS) == before:
                return self._json({"ok": False, "detail": "图库里没有这个任务"}, 400)
            return self._json({"ok": True, "album_id": album_id, "message": "已删除这组图"})
        if path == "/api/plugin/char-swap/styles":
            item = dict(payload)
            item.setdefault("id", "s" + str(len(CUSTOM_STYLES) + 1))
            item["source"] = "phone-custom"
            item["kind"] = "style"
            CUSTOM_STYLES.insert(0, item)
            return self._json({"ok": True, "item": item, "message": "已保存自定义画风"})
        if path == "/api/mobile/char-describe":
            text = str(payload.get("text") or payload.get("description") or "").strip()
            parts = [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]
            caption = text or "1girl, white_hair, red_eyes"
            record = {
                "label": parts[0] if parts else "预览角色",
                "gender": payload.get("gender") or "female",
                "kind": "oc",
                "oc_mode": True,
                "identity": [item for item in parts if "1girl" in item or "1boy" in item or "(oc)" in item] or ["1girl"],
                "appearance": [item for item in parts if "hair" in item or "eyes" in item],
                "clothing": ", ".join(item for item in parts if "dress" in item or "jacket" in item),
                "extra": "",
                "remove": "",
                "char_caption": caption,
            }
            return self._json({"ok": True, "item": record, "generation_calls": 0, "message": "OC 各栏已填好，还没扣 Anlas"})
        if path == "/api/studio/optimize":
            comment = payload.get("comment") or payload.get("patched_comment") or {}
            return self._json({
                "ok": True,
                "comment": comment,
                "texts": {"prompt": comment.get("prompt") or "", "uc": "lowres", "char_captions": []},
                "generation_calls": 0,
            })
        if path == "/api/nai/generate":
            global JOB_SEQ
            work_id = str(payload.get("work_id_str") or payload.get("remote_work_id") or payload.get("work_id") or "")
            if work_id and work_id not in FAV_IDS and work_id != DEMO_ID and not str(work_id).startswith("g"):
                return self._json({"ok": False, "detail": "先收藏入本地库，才能换角和生成"}, 400)
            copies = max(1, min(8, int(payload.get("copies") or 1)))
            slots = max(1, len(PREVIEW_TOKENS) or 1)
            series_pages = payload.get("pages") or []
            page_count = len(series_pages) if series_pages else 1
            total = max(1, page_count * copies)
            JOB_SEQ += 1
            task_id = "previewjob" + str(JOB_SEQ)
            images = []
            for index in range(total):
                images.append({
                    "id": f"preview{index}",
                    "image_url": "/api/mobile/output/preview.png",
                    "thumbnail_url": "/api/mobile/output/preview.png",
                    "page_index": index,
                })
            eta = _estimate_seconds(total, slots)
            JOBS[task_id] = {
                "ok": True,
                "task_id": task_id,
                "album_id": task_id,
                "status": "queued",
                "terminal": False,
                "cancellable": True,
                "retryable": False,
                "done": 0,
                "total": total,
                "pages": page_count,
                "copies": copies,
                "running": 0,
                "concurrency": slots,
                "progress": 2,
                "stage": "queued",
                "stage_label": "排队等待",
                "eta_seconds": eta,
                "eta_text": _format_eta(eta),
                "expected_seconds": eta,
                "title": payload.get("source_title") or "预览生成",
                "items": [],
                "message": "已加入生成队列",
                "_t0": time.time(),
            }
            ALBUMS[:] = [{
                "album_id": task_id,
                "task_id": task_id,
                "title": payload.get("source_title") or "预览生成",
                "image_count": total,
                "cover_url": "/api/mobile/output/preview.png",
                "images": images,
                "source_work_id": work_id,
            }] + [row for row in ALBUMS if row.get("album_id") != task_id]
            OUTPUTS.append({"image_url": "/api/mobile/output/preview.png", "title": "预览生成", "id": "preview"})
            threading.Thread(target=_simulate_job, args=(task_id, total, JOBS[task_id]["title"]), daemon=True).start()
            return self._json({
                "ok": True,
                "task_id": task_id,
                "album_id": task_id,
                "queued": True,
                "concurrency": slots,
                "total": total,
                "pages": page_count,
                "progress": 2,
                "eta_seconds": eta,
                "eta_text": _format_eta(eta),
                "expected_seconds": eta,
                "stage": "queued",
                "stage_label": "排队等待",
                "message": (
                    ("已加入生成队列，" + str(page_count) + " 页收进同一组")
                    if page_count > 1 else "已加入生成队列"
                ) + (f"，{slots} 路并发" if slots > 1 and total > 1 else "") + "，" + _format_eta(eta),
            })
        if path == "/api/pipeline/config":
            if isinstance(payload, dict):
                for key in (
                    "auto_after_generate", "upscale", "metadata", "mosaic",
                    "scale", "mosaic_method", "mosaic_intensity",
                ):
                    if key in payload:
                        PIPELINE_CFG[key] = payload[key]
                PIPELINE_CFG["mosaic_available"] = True
                PIPELINE_CFG["mosaic_mode"] = "light"
            return self._json({"ok": True, "config": dict(PIPELINE_CFG)})
        if path == "/api/pipeline/run":
            return self._json({"ok": True, "message": "已开始"})
        if path == "/api/nai/token":
            PREVIEW_TOKENS[:] = _parse_tokens(str(payload.get("token") or ""))
            n = len(PREVIEW_TOKENS)
            return self._json(_token_payload(
                ("已保存 " + str(n) + " 个 Token，可 " + str(n) + " 路并发") if n else "已清除"
            ))
        if path in {"/api/ai/key", "/api/nai/network"}:
            return self._json({"ok": True, "has_token": True, "has_deepseek": True, "message": "已保存到本机"})
        self._json({"ok": False, "detail": "not found"}, 404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"phone preview http://127.0.0.1:{PORT}/m?standalone=1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Local preview of the standalone phone UI without an Android device."""

from __future__ import annotations

import json
import mimetypes
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
FAV_IDS: list[str] = []
OUTPUTS: list[dict] = []
JOBS: dict[str, dict] = {}
CUSTOM: list[dict] = []


def _search_chars(gender: str, q: str, limit: int) -> list[dict]:
    needle = (q or "").strip().lower()
    bucket = "male" if gender == "male" else "female"
    items: list[dict] = []
    for row in PRESETS.get(bucket, []) or []:
        blob = " ".join(str(row.get(k) or "") for k in ("id", "label", "name", "tag")).lower()
        if needle and needle not in blob:
            continue
        items.append({"reference_id": f"preset:{bucket}:{row.get('id')}", "label": row.get("label") or row.get("id"), "source": "常用角色", "record": row})
    for row in ARK.get(bucket, []) or []:
        blob = " ".join(str(row.get(k) or "") for k in ("id", "label", "name", "tag")).lower()
        if needle and needle not in blob:
            continue
        items.append({"reference_id": f"ark:{bucket}:{row.get('id')}", "label": row.get("label") or row.get("id"), "source": "内置 D 站角色库", "record": row})
        if len(items) >= limit:
            break
    return items[:limit]


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
            return self._json({"ok": True, "standalone": True, "loopback": True, "has_token": True, "has_deepseek": True, "has_ai_key": True})
        if path == "/api/nai/status":
            return self._json({"ok": True, "has_token": True, "has_deepseek": True})
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
            return self._json({
                "ok": True,
                "items": [work],
                "works": [work],
                "page": int(query.get("page") or 1),
                "has_more": False,
                "offline_demo": False,
                "source": "phone-demo",
            })
        if path.startswith("/api/nai/aitag/work/"):
            return self._json(_demo_work())
        if path.startswith("/api/nai/aitag/cover/") or path.startswith("/api/mobile/demo/image/"):
            return self._send(200, _png(0), "image/png")
        if path == "/api/plugin/char-swap/search":
            items = _search_chars(query.get("gender") or "female", query.get("q") or "", int(query.get("limit") or 24))
            return self._json({"ok": True, "items": items, "total": len(items)})
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
            return self._json({"ok": True, "items": OUTPUTS})
        if path == "/api/pipeline/config":
            return self._json({"ok": True, "config": {"auto_after_generate": True, "upscale": True, "metadata": True}})
        if path == "/api/pipeline/status":
            return self._json({"ok": True, "job": {"status": "idle"}, "backlog": {"count": 0}})
        if path.startswith("/api/nai/jobs"):
            task = query.get("task_id") or ""
            return self._json(JOBS.get(task) or {"ok": False, "detail": "generation task not found"}, 404 if task not in JOBS else 200)
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
            return self._json({"ok": True, "favorited": True, "message": "已加入本地库。数据和咒语留下后，可离线换角。"})
        if path == "/api/plugin/char-swap/custom":
            item = dict(payload)
            item.setdefault("id", "c" + str(len(CUSTOM) + 1))
            CUSTOM.insert(0, item)
            return self._json({"ok": True, "item": item, "message": "已保存自定义角色"})
        if path == "/api/mobile/char-describe":
            record = {
                "label": "预览角色",
                "gender": payload.get("gender") or "female",
                "identity": ["1girl"],
                "appearance": ["white_hair", "red_eyes"],
                "char_caption": "1girl, white_hair, red_eyes",
            }
            return self._json({"ok": True, "item": record, "generation_calls": 0, "message": "角色槽已写好，还没扣 Anlas"})
        if path == "/api/studio/optimize":
            comment = payload.get("comment") or payload.get("patched_comment") or {}
            return self._json({
                "ok": True,
                "comment": comment,
                "texts": {"prompt": comment.get("prompt") or "", "uc": "lowres", "char_captions": []},
                "generation_calls": 0,
            })
        if path == "/api/nai/generate":
            task_id = "previewjob01"
            item = {
                "ok": True,
                "image_url": "/api/mobile/output/preview.png",
                "gallery_url": "/api/mobile/output/preview.png",
                "library_id": "gpreview",
                "message": "完成：已入本地库、跑完超分/清元数据、存进相册",
            }
            JOBS[task_id] = {
                "ok": True,
                "task_id": task_id,
                "status": "done",
                "terminal": True,
                "done": 1,
                "total": 1,
                "items": [item],
                "message": item["message"],
            }
            OUTPUTS.append({"image_url": item["image_url"], "title": "预览生成", "id": "preview"})
            return self._json({"ok": True, "task_id": task_id, "queued": True})
        if path == "/api/pipeline/config":
            return self._json({"ok": True, "config": payload})
        if path == "/api/pipeline/run":
            return self._json({"ok": True, "message": "已开始"})
        if path in {"/api/nai/token", "/api/ai/key", "/api/nai/network"}:
            return self._json({"ok": True, "has_token": True, "has_deepseek": True, "message": "已保存到本机"})
        self._json({"ok": False, "detail": "not found"}, 404)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"phone preview http://127.0.0.1:{PORT}/m?standalone=1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

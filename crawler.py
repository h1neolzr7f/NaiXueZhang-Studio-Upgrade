import argparse
import asyncio
import atexit
import json
import sys
import time
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from PIL import Image, ImageOps

from atomic_io import atomic_write_bytes, atomic_write_json
from db import Database
from paths import canonical_path, normalize_config, path_is_within, project_root, relative_to_canonical


class UpstreamRetryableError(RuntimeError):
    pass


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8", buffering=1)

    class Tee:
        def __init__(self, *streams):
            self.streams = streams

        def write(self, data: str) -> None:
            if not data:
                return
            for stream in self.streams:
                stream.write(data)
                stream.flush()

        def flush(self) -> None:
            for stream in self.streams:
                stream.flush()

        def isatty(self) -> bool:
            return getattr(self.streams[0], "isatty", lambda: False)()

    stdout_tee = Tee(sys.__stdout__, log_file)
    stderr_tee = Tee(sys.__stderr__, log_file)
    sys.stdout = stdout_tee
    sys.stderr = stderr_tee

    def _close_logs() -> None:
        try:
            log_file.flush()
        except Exception:
            pass
        try:
            log_file.close()
        except Exception:
            pass
        if sys.stdout is stdout_tee:
            sys.stdout = sys.__stdout__
        if sys.stderr is stderr_tee:
            sys.stderr = sys.__stderr__

    atexit.register(_close_logs)


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_heartbeat(root: Path, phase: str, status: str, message: str = "", **extra: Any) -> None:
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "phase": phase,
        "status": status,
        "message": message,
        **extra,
    }
    atomic_write_json(root / "logs" / "crawler-heartbeat.json", payload)


def write_completed(root: Path, phase: str, message: str = "") -> None:
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "COMPLETED.txt").write_text(
        f"{datetime.now().isoformat(timespec='seconds')} phase={phase} {message}\n",
        encoding="utf-8",
    )


def _safe_preview_component(value: Any, *, default: str = "") -> str:
    component = str(value or default).strip()
    if (
        not component
        or component in {".", ".."}
        or len(component) > 180
        or Path(component).name != component
        or any(char in component for char in ("/", "\\", ":", "\x00"))
        or any(ord(char) < 32 for char in component)
    ):
        raise ValueError(f"unsafe preview path component: {component!r}")
    return component


def preview_local_path(images_dir: Path, image: dict) -> Path:

    image_type = _safe_preview_component(image.get("image_type"), default="NAI")
    author_id = _safe_preview_component(image.get("author_id"), default="unknown")
    file_name = _safe_preview_component(image.get("file_name"))
    name = file_name if Path(file_name).suffix else f"{file_name}.webp"
    if Path(name).suffix.lower() not in {".gif", ".jpeg", ".jpg", ".png", ".webp"}:
        raise ValueError(f"unsupported preview extension: {Path(name).suffix}")
    images_root = canonical_path(images_dir)
    destination = canonical_path(images_root / image_type / author_id / name)
    if not path_is_within(destination, images_root):
        raise ValueError("preview path escapes the image cache")
    return destination


def validate_preview_bytes(
    payload: bytes,
    *,
    content_type: str = "",
    max_bytes: int = 25 * 1024 * 1024,
    max_pixels: int = 80_000_000,
) -> None:
    if not payload:
        raise ValueError("empty preview response")
    if len(payload) > max(1, int(max_bytes)):
        raise ValueError(f"preview response exceeds {max_bytes} bytes")
    mime = str(content_type or "").split(";", 1)[0].strip().lower()
    if mime and not mime.startswith("image/"):
        raise ValueError(f"preview response is not an image: {mime}")
    with Image.open(BytesIO(payload)) as image:
        width, height = image.size
        if width <= 0 or height <= 0 or width * height > max(1, int(max_pixels)):
            raise ValueError(f"preview image dimensions are unsafe: {width}x{height}")
        image.verify()


def preview_url_candidates(config: dict, image: dict) -> list[str]:
    image_type = _safe_preview_component(image.get("image_type"), default="NAI")
    author_id = _safe_preview_component(image.get("author_id"), default="unknown")
    file_name = _safe_preview_component(image.get("file_name"))
    name = file_name if Path(file_name).suffix else f"{file_name}.webp"
    rel = "/".join(quote(part) for part in (image_type, author_id, name))
    candidates: list[str] = []
    cdn = config.get("cdn_url")
    if cdn:
        root = str(cdn).rstrip("/") + "/"
        candidates.append(root + rel)
    image_path = str(image.get("image_path") or "").strip()
    if image_path and cdn:
        path = image_path.replace("\\", "/").lstrip("/")
        path = path.replace("www/pixiv_ai_tag/", "").replace("pixiv_ai_tag/", "")
        if path.lower().endswith(".png"):
            path = path[:-4] + ".webp"
        try:
            safe_path = "/".join(
                quote(_safe_preview_component(part))
                for part in path.split("/")
            )
        except ValueError:
            safe_path = ""
        if safe_path:
            url = str(cdn).rstrip("/") + "/" + safe_path
            if url not in candidates:
                candidates.append(url)
    return candidates


class Crawler:
    def __init__(self, config: dict):
        self.config = config
        query = str(config.get("search_query", "")).lower()
        self._arknights_only = (
            "明日方舟" in config.get("search_query", "")
            or "arknights" in query
            or "アークナイツ" in config.get("search_query", "")
        )
        self._preview_all_local = bool(config.get("preview_all_local", False))
        self.data_dir = Path(config["data_dir"])
        self.images_dir = self.data_dir / "images"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.data_dir / "aitag.db")
        self.db.configure_crawler_wal(
            autocheckpoint_pages=int(
                config.get("crawler_wal_autocheckpoint_pages", 4096) or 4096
            ),
            journal_limit_bytes=int(
                config.get("crawler_wal_journal_limit_mb", 64) or 64
            )
            * 1024
            * 1024,
        )
        self.headers = {"User-Agent": config["user_agent"]}
        self.delay = float(config.get("request_delay_sec", 0.4))
        self.workers = max(1, int(config.get("concurrent_workers", 4)))
        self._base_workers = self.workers
        self._max_workers = max(
            self.workers, int(config.get("max_concurrent_workers", self.workers))
        )
        self._min_delay = float(
            config.get("min_request_delay_sec", self.delay)
        )
        self._max_delay = float(
            config.get("max_request_delay_sec", max(self.delay, 1.5))
        )
        self._preview_workers = max(
            1, int(config.get("preview_workers", self._base_workers))
        )
        self._preview_delay = float(
            config.get("preview_request_delay_sec", 0.4)
        )
        self._preview_timeout = float(config.get("preview_timeout_sec", 20.0))
        self._preview_connect_timeout = float(
            config.get("preview_connect_timeout_sec", 8.0)
        )
        self._preview_max_bytes = max(
            1, int(config.get("preview_max_bytes", 25 * 1024 * 1024))
        )
        self._preview_max_pixels = max(
            1, int(config.get("preview_max_pixels", 80_000_000))
        )
        self._parallel_max_detail_workers = max(
            1, int(config.get("parallel_max_detail_workers", 2))
        )
        self._preview_work_timeout = float(
            config.get("preview_work_timeout_sec", 35.0)
        )
        self._preview_max_attempts = max(
            1, int(config.get("preview_max_attempts", 6))
        )
        self._adaptive_clean_batches = max(
            1,
            int(config.get("adaptive_growth_clean_batches", 2) or 2),
        )
        self._adaptive_latency_target = float(
            config.get("adaptive_latency_target_sec", 10.0) or 10.0
        )
        self._clean_batch_streak = 0
        self._detail_queue_high_watermark = max(
            1,
            int(config.get("detail_queue_high_watermark", 120) or 120),
        )
        self.root = self.data_dir.parent

    def _tune_pace(
        self,
        fail_count: int,
        batch_size: int,
        *,
        retry_count: int = 0,
        p95_latency: float | None = None,
    ) -> None:
        if batch_size <= 0:
            return
        fail_ratio = fail_count / batch_size
        old_workers, old_delay = self.workers, self.delay

        if retry_count > 0 or fail_ratio >= 0.2:
            self._clean_batch_streak = 0
            self.workers = max(1, self.workers - 1)
            self.delay = min(self._max_delay, self.delay + 0.25)
        elif fail_ratio > 0:
            self._clean_batch_streak = 0
            self.delay = min(self._max_delay, self.delay + 0.1)
        else:
            clean_latency = (
                p95_latency is None
                or p95_latency <= self._adaptive_latency_target
            )
            self._clean_batch_streak = (
                self._clean_batch_streak + 1 if clean_latency else 0
            )
            if (
                self._clean_batch_streak >= self._adaptive_clean_batches
                and self.workers < self._max_workers
            ):
                self.workers += 1
                self._clean_batch_streak = 0
            self.delay = max(self._min_delay, self.delay - 0.05)

        if self.workers != old_workers or abs(self.delay - old_delay) > 0.01:
            print(
                f"[tune] workers {old_workers}->{self.workers} "
                f"delay {old_delay:.1f}->{self.delay:.1f}s "
                f"(fail={fail_count}/{batch_size})"
            )

    def _search_page_budget(self, configured: int, pending_details: int) -> int:
        configured = max(0, int(configured))
        pending = max(0, int(pending_details))
        if pending >= self._detail_queue_high_watermark:
            return 0
        if pending >= int(self._detail_queue_high_watermark * 0.5):
            return min(configured, 1)
        return min(configured, 2)

    @staticmethod
    async def _save_detail_entries_async(
        db: Database,
        entries: list[tuple[int, dict[str, Any], str | None, bool, str]],
    ) -> int:
        return await asyncio.to_thread(db.save_details_batch, entries)

    def _sleep(self) -> None:
        time.sleep(self.delay)

    async def _async_sleep(self) -> None:
        await asyncio.sleep(self.delay)

    async def _async_preview_sleep(self) -> None:
        await asyncio.sleep(self._preview_delay)

    def _request_json_sync(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        retries: int = 5,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = client.request(method, url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                wait = min(self.delay * attempt * 2, 30.0)
                print(
                    f"[retry] {url} attempt={attempt}/{retries} err={exc} wait={wait:.1f}s"
                )
                time.sleep(wait)
        assert last_error is not None
        raise UpstreamRetryableError(str(last_error)) from last_error

    async def _request_async(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        retries: int = 5,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = await client.request(method, url, params=params)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                wait = min(self.delay * attempt * 2, 15.0)
                print(
                    f"[retry] {url} attempt={attempt}/{retries} err={exc} wait={wait:.1f}s"
                )
                await asyncio.sleep(wait)
        assert last_error is not None
        raise last_error

    async def _request_preview_async(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        retries: int = 3,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                response = await client.request(method, url)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"retryable status {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                wait = min(self._preview_delay * attempt * 2, 8.0)
                print(
                    f"[preview-retry] {url} attempt={attempt}/{retries} "
                    f"err={exc} wait={wait:.1f}s"
                )
                await asyncio.sleep(wait)
        assert last_error is not None
        raise last_error

    def crawl_search_pages(
        self, client: httpx.Client, *, page_budget: int | None = None
    ) -> bool:
        query = self.config["search_query"]
        page_size = int(self.config["page_size"])
        sort = self.config.get("search_sort", "new")
        time_range = self.config.get("search_time_range", "all")
        max_pages = int(self.config.get("search_max_pages", 0) or 0)
        start_page = int(self.db.get_state("search_page", "1"))
        total_pages = int(self.db.get_state("search_total_pages", "0"))
        pages_done = max(start_page - 1, 0)

        page = start_page
        fetched = 0
        upstream_waiting = False
        known_streak = 0
        stop_after_known = max(
            0,
            int(self.config.get("search_stop_after_known_pages", 0) or 0),
        )
        while True:
            if page_budget is not None and fetched >= page_budget:
                break
            if max_pages > 0 and pages_done >= max_pages:
                print(
                    f"[search] session cap {max_pages} pages reached; "
                    "resume next run from saved search_page"
                )
                break

            try:
                response = self._request_json_sync(
                    client,
                    "GET",
                    f"{self.config['base_url']}/api/ai_works_search",
                    params={
                        "q": query,
                        "page": page,
                        "page_size": page_size,
                        "sort": sort,
                        "time_range": time_range,
                    },
                )
            except UpstreamRetryableError as exc:
                message = f"search page {page} upstream retryable failure: {exc}"
                print(f"[search] {message}; will resume next run")
                write_heartbeat(
                    self.root,
                    "search",
                    "waiting",
                    message,
                    page=page,
                    search_page=start_page,
                    fetched=fetched,
                )
                upstream_waiting = True
                break
            data = response.json()
            if data.get("error"):
                print(
                    f"[search] API error on page {page}: {data.get('error')} "
                    f"{data.get('message') or ''}".strip()
                )
                break
            items = data.get("items") or []
            total = int(data.get("total") or 0)
            refreshed_total_pages = (
                (total + page_size - 1) // page_size if total > 0 else 0
            )
            if refreshed_total_pages and refreshed_total_pages != total_pages:
                total_pages = refreshed_total_pages
                self.db.set_state("search_total_pages", str(total_pages))
                self.db.set_state("search_total", str(total))

            if not items and total > 0:
                print(
                    f"[search] page {page} returned 0 items but total={total}; "
                    "treating as transient failure, will retry next run"
                )
                write_heartbeat(
                    self.root,
                    "search",
                    "waiting",
                    "upstream returned an empty non-terminal page",
                    page=page,
                    total=total,
                )
                upstream_waiting = True
                break

            crawled_at = now_iso()
            batch = self.db.upsert_list_items_batch(items, crawled_at)
            already_complete = int(batch.get("already_complete") or 0)

            top_bm = int((items[0] or {}).get("total_bookmarks") or 0) if items else 0
            print(
                f"[search] sort={sort} page {page}/{total_pages or '?'} "
                f"items={len(items)} already_complete={already_complete} "
                f"top_bm={top_bm} total_saved={self.db.count_works()}"
            )

            self.db.set_state("search_page", str(page + 1))
            pages_done += 1
            fetched += 1
            if items and already_complete == len(items):
                known_streak += 1
            else:
                known_streak = 0
            if stop_after_known and known_streak >= stop_after_known:
                self.db.set_state("search_done", "1")
                self.db.set_state(
                    "search_completion_reason",
                    f"known_pages:{known_streak}",
                )
                print(
                    f"[search] incremental scan complete after "
                    f"{known_streak} consecutive known pages"
                )
                break
            if total_pages and page >= total_pages:
                self.db.set_state("search_done", "1")
                print("[search] done")
                break
            if len(items) < page_size and total_pages <= 0 and total <= 0:
                self.db.set_state("search_done", "1")
                print(
                    f"[search] done (partial page {len(items)}/{page_size}, "
                    "upstream total unknown)"
                )
                break
            if not items:
                if page == 1 and total == 0:
                    self.db.set_state("search_done", "1")
                    print("[search] done (empty result)")
                    break
                if total <= 0 and page > 1:
                    self.db.set_state("search_done", "1")
                    print("[search] done (empty page, upstream total unknown)")
                    break
                break
            if max_pages > 0 and pages_done >= max_pages:
                print(
                    f"[search] session cap {max_pages} pages reached; "
                    "resume next run from saved search_page"
                )
                break
            page += 1
            self._sleep()
        return upstream_waiting

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
        fail_counter: list[int],
        skip_counter: list[int],
        work_id: int,
    ) -> None:
        async with sem:
            if self.db.has_detail(work_id):
                skip_counter[0] += 1
                return
            url = f"{self.config['base_url']}/api/work/{work_id}"
            try:
                response = await self._request_async(client, "GET", url, retries=5)
                detail = response.json()
                self.db.save_detail(work_id, detail, None, False, now_iso())
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    self.db.save_detail(
                        work_id,
                        {"work": {"id": work_id}, "images": []},
                        None,
                        False,
                        now_iso(),
                    )
                    print(f"[detail] 404 saved empty detail {work_id}")
                    return
                fail_counter[0] += 1
                print(f"[detail] failed {work_id}: {exc}")
            except Exception as exc:
                fail_counter[0] += 1
                print(f"[detail] failed {work_id}: {exc}")
            finally:
                await self._async_sleep()

    async def crawl_details_async(
        self,
        *,
        max_batches: int | None = None,
    ) -> None:
        print(f"[detail] workers={self.workers} delay={self.delay}s")
        timeout = httpx.Timeout(90.0, connect=30.0)
        limits = httpx.Limits(
            max_connections=self._max_workers + 2,
            max_keepalive_connections=self._max_workers,
        )
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=timeout,
            follow_redirects=True,
            limits=limits,
        ) as client:
            batches_done = 0
            while True:
                if max_batches is not None and batches_done >= max_batches:
                    break
                sem = asyncio.Semaphore(self.workers)
                batch_size = max(4, self.workers * 8)
                pending = self.db.pending_detail_ids(
                    batch_size, arknights_only=self._arknights_only
                )
                if not pending:
                    print("[detail] done")
                    break

                fail_counter = [0]
                skip_counter = [0]
                batch_started = time.monotonic()
                await asyncio.gather(
                    *[
                        self._fetch_detail(
                            client, sem, fail_counter, skip_counter, work_id
                        )
                        for work_id in pending
                    ],
                    return_exceptions=True,
                )
                batches_done += 1
                elapsed = time.monotonic() - batch_started
                done = self.db.count_details()
                total = self.db.count_works()
                fetched = len(pending) - fail_counter[0] - skip_counter[0]
                rate = fetched / elapsed if elapsed > 0 else 0
                print(
                    f"[detail] batch={len(pending)} fetched={fetched} "
                    f"skip={skip_counter[0]} fail={fail_counter[0]} "
                    f"done={done}/{total} rate={rate:.2f}/s elapsed={elapsed:.0f}s "
                    f"workers={self.workers} delay={self.delay:.1f}s"
                )
                write_heartbeat(
                    self.root,
                    "detail",
                    "running",
                    "detail batch finished",
                    done=done,
                    total=total,
                    fail=fail_counter[0],
                    pending=len(pending),
                )
                self._tune_pace(fail_counter[0], len(pending))
                if fail_counter[0] >= max(2, len(pending) // 4):
                    cooldown = min(45.0, 10.0 + fail_counter[0] * 2)
                    print(
                        f"[detail] cooldown {cooldown:.0f}s "
                        f"(server 502/503, backing off)"
                    )
                    await asyncio.sleep(cooldown)

    def _preview_arknights_only(self) -> bool:
        if self._preview_all_local:
            return False
        return self._arknights_only

    async def _fetch_cover_impl(
        self,
        client: httpx.AsyncClient,
        work_id: int,
        cover_only: bool,
    ) -> bool:
        try:
            if cover_only and self.db.has_preview(work_id):
                return False
            images = self.db.pending_images_for_work(
                work_id,
                cover_only=bool(cover_only),
            )
            if not images and cover_only:
                fallback = self.db.cover_image_from_list_json(work_id)
                if fallback:
                    images = [fallback]

            if not images:
                attempts = self.db.bump_preview_attempts(work_id)
                print(f"[preview] no image candidates {work_id} try={attempts}")
                return False

            downloaded_any = False
            for row in images:
                try:
                    image_path = row["image_path"] or ""
                except (KeyError, IndexError, TypeError):
                    image_path = ""
                image = {
                    "image_type": row["image_type"],
                    "author_id": row["author_id"],
                    "file_name": row["file_name"],
                    "image_path": image_path,
                }
                page_index = int(row["page_index"])
                local_path = preview_local_path(self.images_dir, image)
                local_path.parent.mkdir(parents=True, exist_ok=True)

                cached_valid = False
                if local_path.exists():
                    try:
                        validate_preview_bytes(
                            local_path.read_bytes(),
                            max_bytes=self._preview_max_bytes,
                            max_pixels=self._preview_max_pixels,
                        )
                        cached_valid = True
                    except Exception as exc:
                        print(
                            f"[preview] invalid cached image {local_path.name}: {exc}"
                        )

                if not cached_valid:
                    downloaded = False
                    for url in preview_url_candidates(self.config, image):
                        try:
                            response = await self._request_preview_async(
                                client, "GET", url, retries=2
                            )
                            content_length = response.headers.get("content-length", "")
                            if content_length:
                                try:
                                    if int(content_length) > self._preview_max_bytes:
                                        raise ValueError(
                                            "preview response exceeds configured size limit"
                                        )
                                except ValueError as exc:
                                    if "exceeds" in str(exc):
                                        raise
                            payload = response.content
                            validate_preview_bytes(
                                payload,
                                content_type=response.headers.get("content-type", ""),
                                max_bytes=self._preview_max_bytes,
                                max_pixels=self._preview_max_pixels,
                            )
                            atomic_write_bytes(local_path, payload)
                            downloaded = True
                            break
                        except httpx.HTTPStatusError as exc:
                            if exc.response.status_code == 404:
                                continue
                        except Exception:
                            continue
                    if not downloaded:
                        continue

                # 规范约定：local_path 相对 images_dir 存储（如 NAI/...），
                # 与 intake 一致；读取侧经 paths.normalize_image_relative 兼容旧行。
                rel_path = relative_to_canonical(local_path, self.images_dir)
                self.db.mark_image_downloaded(
                    work_id,
                    page_index,
                    rel_path,
                    cover_only=cover_only,
                )
                downloaded_any = True
                if cover_only:
                    break
            if not downloaded_any:
                raise RuntimeError(f"all preview urls failed for {work_id}")
            self.db.reset_preview_attempts(work_id)
            return True
        except Exception as exc:
            attempts = self.db.bump_preview_attempts(work_id)
            print(f"[preview] failed {work_id} try={attempts}: {exc}")
            return False

    async def _fetch_cover(
        self,
        client: httpx.AsyncClient,
        sem: asyncio.Semaphore,
        success_counter: list[int],
        fail_counter: list[int],
        skip_counter: list[int],
        work_id: int,
        cover_only: bool,
    ) -> None:
        async with sem:
            if cover_only and self.db.has_preview(work_id):
                skip_counter[0] += 1
                return
            try:
                success = await asyncio.wait_for(
                    self._fetch_cover_impl(client, work_id, cover_only),
                    timeout=self._preview_work_timeout,
                )
                if success:
                    success_counter[0] += 1
                else:
                    fail_counter[0] += 1
            except asyncio.TimeoutError:
                attempts = self.db.bump_preview_attempts(work_id)
                fail_counter[0] += 1
                print(
                    f"[preview] timeout {work_id} try={attempts} "
                    f"after {self._preview_work_timeout:.0f}s"
                )
            finally:
                await self._async_preview_sleep()

    async def crawl_previews_async(self, *, wait_for_details: bool = False) -> None:
        cover_only = self.config.get("preview_mode", "cover_only") == "cover_only"
        mode_label = "cover_only" if cover_only else "all"
        parallel_note = " parallel=on" if wait_for_details else ""
        print(
            f"[preview] mode={mode_label} workers={self._preview_workers} "
            f"delay={self._preview_delay}s{parallel_note}"
        )

        timeout = httpx.Timeout(
            self._preview_timeout, connect=self._preview_connect_timeout
        )
        limits = httpx.Limits(
            max_connections=self._preview_workers + 2,
            max_keepalive_connections=self._preview_workers,
        )

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=timeout,
            follow_redirects=True,
            limits=limits,
        ) as client:
            while True:
                sem = asyncio.Semaphore(self._preview_workers)
                batch_size = max(3, self._preview_workers * 3)
                pending = self.db.pending_preview_work_ids(
                    batch_size,
                    max_attempts=self._preview_max_attempts,
                    arknights_only=self._preview_arknights_only(),
                )
                if not pending:
                    if (
                        wait_for_details
                        and self.db.count_pending_details(
                            arknights_only=self._arknights_only
                        )
                        > 0
                    ):
                        await asyncio.sleep(3)
                        continue
                    print("[preview] done")
                    break

                skip_counter = [0]
                success_counter = [0]
                fail_counter = [0]
                batch_started = time.monotonic()
                await asyncio.gather(
                    *[
                        self._fetch_cover(
                            client,
                            sem,
                            success_counter,
                            fail_counter,
                            skip_counter,
                            work_id,
                            cover_only,
                        )
                        for work_id in pending
                    ],
                    return_exceptions=True,
                )
                elapsed = time.monotonic() - batch_started
                previews = self.db.count_previews()
                details = self.db.count_details()
                fetched = success_counter[0]
                rate = fetched / elapsed if elapsed > 0 else 0
                print(
                    f"[preview] batch={len(pending)} fetched={fetched} "
                    f"fail={fail_counter[0]} skip={skip_counter[0]} "
                    f"covers={previews}/{details} "
                    f"local_images={self.db.count_downloaded_images()} "
                    f"rate={rate:.2f}/s elapsed={elapsed:.0f}s"
                )
                write_heartbeat(
                    self.root,
                    "preview",
                    "running",
                    "preview batch finished",
                    covers=previews,
                    details=details,
                    pending=len(pending),
                    fetched=fetched,
                    failed=fail_counter[0],
                    skipped=skip_counter[0],
                )

    async def crawl_parallel_async(
        self,
        *,
        max_detail_batches: int | None = None,
    ) -> None:
        if self._max_workers > self._parallel_max_detail_workers:
            self._max_workers = self._parallel_max_detail_workers
        if self.workers > self._parallel_max_detail_workers:
            self.workers = self._parallel_max_detail_workers
        print(
            "[parallel] detail + preview together "
            f"(detail: {self.workers}w/{self.delay}s cap={self._max_workers}, "
            f"preview: {self._preview_workers}w/{self._preview_delay}s "
            f"timeout={self._preview_timeout:.0f}s)"
        )
        results = await asyncio.gather(
            self.crawl_details_async(max_batches=max_detail_batches),
            self.crawl_previews_async(wait_for_details=True),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                print(f"[parallel] task crashed: {result!r}")
                raise result

    def _reconcile_local_state(self) -> None:
        stats = self.db.reconcile_local_covers(self.data_dir)
        if stats["works_marked"] or stats["image_rows_updated"]:
            print(
                "[reconcile] synced local covers: "
                f"works={stats['works_marked']} "
                f"image_rows={stats['image_rows_updated']}"
            )

    def _log_queue_summary(self) -> None:
        ark_detail = self._arknights_only
        ark_preview = self._preview_arknights_only()
        detail_pending = self.db.count_pending_details(arknights_only=ark_detail)
        preview_pending = self.db.count_pending_previews(
            arknights_only=ark_preview, max_attempts=self._preview_max_attempts
        )
        preview_exhausted = self.db.count_exhausted_previews(
            arknights_only=ark_preview, max_attempts=self._preview_max_attempts
        )
        print(
            "[queue] "
            f"detail_pending={detail_pending} "
            f"preview_pending={preview_pending} "
            f"preview_exhausted={preview_exhausted} "
            f"(filter={'arknights' if ark_detail else 'all'})"
        )
        write_heartbeat(
            self.root,
            "queue",
            "running",
            "queue summary",
            detail_pending=detail_pending,
            preview_pending=preview_pending,
            preview_exhausted=preview_exhausted,
        )

    def _has_pending_details(self) -> bool:
        return self.db.count_pending_details(arknights_only=self._arknights_only) > 0

    def _has_pending_previews(self) -> bool:
        return bool(
            self.db.pending_preview_work_ids(
                1,
                max_attempts=self._preview_max_attempts,
                arknights_only=self._preview_arknights_only(),
            )
        )

    def _mark_current_task_complete(self, phase: str) -> None:
        detail_pending = self.db.count_pending_details(arknights_only=self._arknights_only)
        preview_pending = self.db.count_pending_previews(
            arknights_only=self._preview_arknights_only(),
            max_attempts=self._preview_max_attempts,
        )
        preview_exhausted = self.db.count_exhausted_previews(
            arknights_only=self._preview_arknights_only(),
            max_attempts=self._preview_max_attempts,
        )
        message = (
            f"detail_pending={detail_pending} "
            f"preview_pending={preview_pending} "
            f"preview_exhausted={preview_exhausted}"
        )
        write_heartbeat(
            self.root,
            phase,
            "complete",
            message,
            detail_pending=detail_pending,
            preview_pending=preview_pending,
            preview_exhausted=preview_exhausted,
        )
        write_completed(self.root, phase, message)

    def run(self, phase: str) -> None:
        search_sort = self.config.get("search_sort", "new")
        search_batch = max(1, int(self.config.get("search_batch_pages", 8)))
        search_max = int(self.config.get("search_max_pages", 0) or 0)
        self._reconcile_local_state()
        self._log_queue_summary()
        print(
            f"[config] workers={self.workers} delay={self.delay}s "
            f"preview={self.config.get('preview_mode', 'cover_only')} "
            f"sort={search_sort} batch={search_batch} max_pages={search_max or '∞'}"
        )
        timeout = httpx.Timeout(60.0, connect=30.0)
        with httpx.Client(
            headers=self.headers, timeout=timeout, follow_redirects=True
        ) as client:
            if phase == "search":
                if self.db.get_state("search_done", "0") == "1":
                    print("[search] already complete, skipping list crawl")
                else:
                    self.crawl_search_pages(client)
            elif phase == "all":
                while True:
                    search_waiting = False
                    search_done = self.db.get_state("search_done", "0") == "1"
                    pages_done = max(int(self.db.get_state("search_page", "1")) - 1, 0)
                    if not search_done:
                        budget = search_batch
                        if search_max > 0:
                            budget = min(budget, max(0, search_max - pages_done))
                        if budget > 0:
                            search_waiting = self.crawl_search_pages(
                                client, page_budget=budget
                            )
                    elif search_done:
                        pass  # 列表已爬完，不重复请求搜索 API

                    needs_detail = self._has_pending_details()
                    needs_preview = self._has_pending_previews()
                    search_done = self.db.get_state("search_done", "0") == "1"
                    if not needs_detail and not needs_preview:
                        if search_done:
                            print("[done] search + detail + preview complete")
                            self._mark_current_task_complete("all")
                            break
                        if search_waiting:
                            print(
                                "[search] upstream waiting and no local queue; "
                                "clean exit so supervisor can back off"
                            )
                            break
                        continue

                    try:
                        asyncio.run(self.crawl_parallel_async())
                    except Exception as exc:
                        print(
                            f"[crash] parallel crawl stopped: {exc!r}; "
                            "retrying in 15s (checkpoint safe)"
                        )
                        import traceback

                        traceback.print_exc()
                        time.sleep(15)
                        continue

                    needs_detail = self._has_pending_details()
                    needs_preview = self._has_pending_previews()
                    search_done = self.db.get_state("search_done", "0") == "1"
                    if not needs_detail and not needs_preview and search_done:
                        print("[done] detail + preview complete")
                        self._mark_current_task_complete("all")
                        break
                    print(
                        f"[resume] more work remains "
                        f"(details={self.db.count_details()}/{self.db.count_works()}, "
                        f"previews={self.db.count_previews()}, "
                        f"search_done={int(search_done)}); continuing"
                    )
            elif phase == "detail":
                asyncio.run(self.crawl_details_async())
                if not self._has_pending_details():
                    self._mark_current_task_complete("detail")
            elif phase == "preview":
                asyncio.run(self.crawl_previews_async())
                if not self._has_pending_previews():
                    self._mark_current_task_complete("preview")

        print(
            json.dumps(
                {
                    "works": self.db.count_works(),
                    "details": self.db.count_details(),
                    "works_with_all_previews": self.db.count_previews(),
                    "images_downloaded": self.db.count_downloaded_images(),
                },
                ensure_ascii=False,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="disabled legacy upstream crawler")
    parser.add_argument(
        "--phase",
        choices=["all", "search", "detail", "preview"],
        default="all",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("config.json")),
    )
    args = parser.parse_args()
    root = Path(args.config).resolve().parent
    setup_logging(root / "logs" / "crawl.log")
    config = normalize_config(load_config(Path(args.config)), root)
    print(f"[start] {datetime.now().isoformat()} phase={args.phase}", flush=True)
    if not bool(config.get("legacy_aitag_crawler_enabled", False)):
        message = "legacy upstream crawler is disabled; use pixiv_nai_crawler.py"
        print(f"[disabled] {message}", flush=True)
        write_heartbeat(root, args.phase, "disabled", message)
        return
    write_heartbeat(root, args.phase, "starting", "crawler process started")
    try:
        Crawler(config).run(args.phase)
    except Exception:
        import traceback

        write_heartbeat(root, args.phase, "crashed", "crawler process crashed")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()

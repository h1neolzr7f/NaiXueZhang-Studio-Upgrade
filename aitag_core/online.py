"""On-demand AITag discovery client.

AITag is treated as a remote discovery source, not as a second gallery
database.  The client only requests JSON metadata, keeps a bounded HTTPS
response cache, and leaves image downloads and persistence to explicit caller
actions.  This makes the online path useful when the local catalog is cold
while keeping the offline path deterministic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode, urlparse

import httpx

from .external import (
    AitagConfig,
    AitagSearchPage,
    AitagWorkDetail,
    aitag_work_is_nai,
    aitag_work_is_safe,
    normalize_aitag_config,
    normalize_aitag_detail,
    normalize_aitag_search,
)
from .storage.http_cache import DiskResponseCache

AITAG_SITE_URL = "https://aitag.win"
AITAG_IMAGE_ORIGIN = "https://ai-img.10118899.xyz"
AITAG_PAGE_SIZE = 60
AITAG_TIMEOUT_SECONDS = 30.0
AITAG_CACHE_TTL_SECONDS = 600.0
AITAG_CACHE_MAX_BYTES = 64 * 1024 * 1024
_WORK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")
_SORT_MAP = {
    "recent": "new",
    "new": "new",
    "popular": "popular",
    "hot": "popular",
    "monthly": "popular",
    "relevance": "relevance",
}
_TIME_RANGE_MAP = {
    "all": "all",
    "week": "week",
    "month": "month",
    "current": "current",
}


class AitagClientError(RuntimeError):
    """A user-safe error raised when remote AITag discovery is unavailable."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class AitagSearchRequest:
    page: int = 1
    page_size: int = AITAG_PAGE_SIZE
    query: str = ""
    prompt: str = ""
    sort: str = "new"
    time_range: str = "all"

    def normalized(self) -> "AitagSearchRequest":
        page = max(1, min(int(self.page or 1), 10_000))
        # AITag currently enforces one public page size (60). Keep the local
        # route forgiving while always sending the contract the upstream API
        # accepts.
        page_size = AITAG_PAGE_SIZE
        query = str(self.query or "").strip()[:2_000]
        prompt = str(self.prompt or "").strip()[:2_000]
        sort = _SORT_MAP.get(str(self.sort or "recent").strip().casefold(), "new")
        raw_range = str(self.time_range or "all").strip()
        if _PERIOD_RE.fullmatch(raw_range):
            time_range = raw_range
        else:
            time_range = _TIME_RANGE_MAP.get(raw_range.casefold(), "all")
        return AitagSearchRequest(page, page_size, query, prompt, sort, time_range)


def _upstream_search(request: AitagSearchRequest) -> tuple[str, dict[str, Any]]:
    """Pick the official AITag endpoint that actually implements this sort.

    ``/api/ai_works_search`` currently ignores ``sort`` and always returns the
    newest ingest order. Official 热门 is the monthly rank board, not a search
    sort alias.
    """

    if request.sort == "popular":
        params: dict[str, Any] = {
            "page": request.page,
            "page_size": request.page_size,
        }
        if request.query:
            params["q"] = request.query
        if request.prompt:
            params["prompt"] = request.prompt
        if _PERIOD_RE.fullmatch(request.time_range):
            params["period"] = request.time_range
            return "/api/rank/monthly", params
        return "/api/rank/monthly/real", params
    return (
        "/api/ai_works_search",
        {
            "page": request.page,
            "page_size": request.page_size,
            "q": request.query,
            "prompt": request.prompt,
            "sort": request.sort,
            "time_range": request.time_range,
        },
    )


def validate_aitag_base_url(value: str = AITAG_SITE_URL) -> str:
    """Accept only the canonical, fixed AITag HTTPS origin.

    The origin is deliberately not a general mirror setting.  Allowing a
    caller-controlled host, port, path, credentials or parser-dependent URL
    would turn this discovery Adapter into an SSRF primitive.
    """

    raw = str(value or AITAG_SITE_URL).strip().rstrip("/")
    parsed = urlparse(raw)
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname != "aitag.win"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("AITag online base URL must be exactly https://aitag.win")
    return AITAG_SITE_URL


def _validate_response_origin(response: Any) -> None:
    """Reject redirects, including ones already followed by an injected client."""

    if getattr(response, "history", None):
        raise AitagClientError("AITag redirects are not accepted")
    response_url = getattr(response, "url", None)
    if response_url is None:
        return
    parsed = urlparse(str(response_url))
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname != "aitag.win"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise AitagClientError("AITag response escaped the fixed HTTPS origin")


class AitagClient:
    """Small synchronous client used by the FastAPI read/import bridge."""

    def __init__(
        self,
        *,
        base_url: str = AITAG_SITE_URL,
        cache_root: Path | str | None = None,
        cache_ttl_seconds: float = AITAG_CACHE_TTL_SECONDS,
        cache_max_bytes: int = AITAG_CACHE_MAX_BYTES,
        timeout_seconds: float = AITAG_TIMEOUT_SECONDS,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = validate_aitag_base_url(base_url)
        self.cache = DiskResponseCache(
            cache_root or Path("data") / ".cache" / "aitag-online",
            ttl_seconds=cache_ttl_seconds,
            max_bytes=cache_max_bytes,
        )
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(
            timeout=float(timeout_seconds),
            # Do not follow a server-controlled redirect to an arbitrary host.
            # The only upstream origin is the allowlisted AITag site.
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "Pixiv-NAI-Gallery/aitag"},
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{str(path).lstrip('/')}"

    @staticmethod
    def _cache_url(url: str, params: Mapping[str, Any] | None) -> str:
        pairs = [(str(key), str(value)) for key, value in (params or {}).items() if value is not None]
        return f"{url}?{urlencode(sorted(pairs))}" if pairs else url

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Mapping[str, Any] | list[Any]:
        url = self._url(path)
        cache_url = self._cache_url(url, params)
        cached = self.cache.get(cache_url)
        if cached:
            try:
                value = json.loads(cached.decode("utf-8"))
                if isinstance(value, (Mapping, list)):
                    return value
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass

        try:
            response = self.http_client.get(url, params=dict(params or {}))
        except Exception as exc:  # httpx and injected transports use different base errors
            raise AitagClientError(f"AITag request failed: {exc}") from exc
        status_code = int(getattr(response, "status_code", 0) or 0)
        _validate_response_origin(response)
        if 300 <= status_code < 400:
            raise AitagClientError(
                "AITag redirects are not accepted",
                status_code=status_code,
            )
        if status_code == 404 and allow_404:
            return {}
        if status_code < 200 or status_code >= 300:
            detail = ""
            try:
                detail = str(response.text or "").strip()[:300]
            except Exception:
                pass
            suffix = f": {detail}" if detail else ""
            raise AitagClientError(
                f"AITag returned HTTP {status_code}{suffix}",
                status_code=status_code or None,
            )
        try:
            payload = response.json()
        except Exception as exc:
            try:
                payload = json.loads(bytes(response.content).decode("utf-8"))
            except Exception:
                raise AitagClientError("AITag returned invalid JSON", status_code=status_code) from exc
        if not isinstance(payload, (Mapping, list)):
            raise AitagClientError("AITag returned an unsupported JSON payload", status_code=status_code)
        try:
            self.cache.put(
                cache_url,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            )
        except (OSError, ValueError):
            # A full/read-only cache never makes online discovery fail.
            pass
        return payload

    def get_config(self, *, refresh: bool = False) -> AitagConfig:
        # ``refresh`` is intentionally a cache clear for one known endpoint;
        # no arbitrary cache key comes from the browser.
        if refresh:
            self.cache.clear_url(self._url("/api/config")) if hasattr(self.cache, "clear_url") else None
        payload = self._request_json("/api/config")
        return normalize_aitag_config(payload)

    def get_image(self, image_type: str, author_id: str, file_name: str) -> tuple[bytes, str]:
        """Read one bounded image from the fixed AITag CDN without persistence."""

        parts = [str(image_type or ""), str(author_id or ""), str(file_name or "")]
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", parts[0])
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}", parts[1])
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,180}\.webp", parts[2], re.IGNORECASE)
        ):
            raise ValueError("invalid AITag image path")
        from urllib.parse import quote

        url = AITAG_IMAGE_ORIGIN + "/" + "/".join(quote(part, safe="") for part in parts)
        try:
            response = self.http_client.get(url, params={})
        except Exception as exc:
            raise AitagClientError(f"AITag image request failed: {exc}") from exc
        status_code = int(getattr(response, "status_code", 0) or 0)
        if getattr(response, "history", None) or 300 <= status_code < 400:
            raise AitagClientError("AITag image redirects are not accepted", status_code=status_code)
        response_url = getattr(response, "url", None)
        if response_url is not None:
            parsed = urlparse(str(response_url))
            if parsed.scheme.casefold() != "https" or parsed.hostname != "ai-img.10118899.xyz" or parsed.port not in (None, 443):
                raise AitagClientError("AITag image response escaped the fixed CDN origin")
        if status_code != 200:
            raise AitagClientError("AITag image was unavailable", status_code=status_code or None)
        content = bytes(getattr(response, "content", b"") or b"")
        if not content or len(content) > 25 * 1024 * 1024:
            raise AitagClientError("AITag image exceeded the display limit")
        headers = getattr(response, "headers", {}) or {}
        content_type = str(headers.get("content-type", "image/webp")).split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            raise AitagClientError("AITag image returned an invalid content type")
        return content, content_type

    def search(
        self,
        *,
        page: int = 1,
        page_size: int = AITAG_PAGE_SIZE,
        query: str = "",
        prompt: str = "",
        sort: str = "new",
        time_range: str = "all",
        nai_only: bool = True,
        safe_only: bool = True,
    ) -> AitagSearchPage:
        request = AitagSearchRequest(page, page_size, query, prompt, sort, time_range).normalized()
        path, params = _upstream_search(request)
        payload = self._request_json(
            path,
            params=params,
            allow_404=True,
        )
        result = normalize_aitag_search(
            payload,
            query=request.query or request.prompt,
            page=request.page,
            page_size=request.page_size,
        )
        works = tuple(
            work
            for work in result.works
            if (not nai_only or aitag_work_is_nai(work))
            and (not safe_only or aitag_work_is_safe(work))
        )
        return AitagSearchPage(
            query=result.query,
            page=result.page,
            page_size=result.page_size,
            total=result.total,
            has_more=result.has_more,
            works=works,
        )

    def get_work(self, work_id: str, *, refresh: bool = False) -> AitagWorkDetail:
        identifier = str(work_id or "").strip()
        if not _WORK_ID_RE.fullmatch(identifier):
            raise ValueError("AITag work id is invalid")
        payload = self._request_json(f"/api/work/{identifier}")
        return normalize_aitag_detail(payload)

    def status(self) -> dict[str, Any]:
        return {
            "configured": True,
            "base_url": self.base_url,
            "cache": self.cache.stats(),
            "cache_ttl_seconds": self.cache.ttl_seconds,
        }

    def clear_cache(self) -> int:
        return self.cache.clear()

    def close(self) -> None:
        if self._owns_client:
            try:
                self.http_client.close()
            except Exception:
                pass


__all__ = [
    "AITAG_PAGE_SIZE",
    "AITAG_SITE_URL",
    "AitagClient",
    "AitagClientError",
    "AitagSearchRequest",
    "validate_aitag_base_url",
]

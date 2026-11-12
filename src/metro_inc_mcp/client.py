"""HTTP client for a Metro inc. banner website: Chrome TLS impersonation, request spacing, retries."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession, Response
from curl_cffi.requests.exceptions import RequestException

from .config import Settings
from .errors import CloudflareBlocked, RateLimited, SiteMaintenance, SiteUnreachable, UpstreamError

log = logging.getLogger(__name__)

AJAX_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}
RETRY_DELAYS_429 = (30.0, 60.0)
CACHE_TTL = 300.0


def is_maintenance_url(url: str) -> bool:
    """During maintenance every path answers 302 to http://maintenance.metro.ca/ (seen on metro.ca 2026-11-09)."""
    return (urlparse(url).hostname or "").startswith("maintenance.")


class GroceryClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.banner.base_url
        self.site = self.base_url.removeprefix("https://www.")
        self.session = AsyncSession(
            impersonate=settings.impersonate,
            headers={"Accept-Language": settings.language},  # the site picks the language from the path
            timeout=30,
        )
        self._lock = asyncio.Lock()  # one request at a time, spaced by min_interval
        self._last_request = 0.0
        self._cache: dict[tuple[str, str, str], tuple[float, str]] = {}

    async def close(self) -> None:
        await self.session.close()

    async def _wait_turn(self) -> None:
        delay = self._last_request + self.settings.min_interval - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    async def request(self, method: str, path: str, *, ajax: bool = False, **kwargs: Any) -> Response:
        headers = {**(AJAX_HEADERS if ajax else {}), **kwargs.pop("headers", {})}
        url = path if path.startswith("http") else self.base_url + path
        async with self._lock:
            for attempt in range(len(RETRY_DELAYS_429) + 1):
                await self._wait_turn()
                try:
                    resp = await self.session.request(method, url, headers=headers, **kwargs)
                except RequestException as e:  # timeout, DNS, connection reset: no HTTP answer at all
                    self._last_request = time.monotonic()
                    log.warning("%s %s failed: %s", method, path, type(e).__name__)
                    raise SiteUnreachable(self.site) from e
                self._last_request = time.monotonic()
                log.debug("%s %s -> %s", method, path, resp.status_code)
                if resp.status_code != 429:
                    break
                if attempt == len(RETRY_DELAYS_429):
                    raise RateLimited(self.site)
                log.warning("429 on %s, retrying in %ss", path, RETRY_DELAYS_429[attempt])
                await asyncio.sleep(RETRY_DELAYS_429[attempt])
        if resp.headers.get("cf-mitigated") == "challenge":
            raise CloudflareBlocked(self.site)
        if is_maintenance_url(str(resp.url)) or is_maintenance_url(resp.headers.get("location") or ""):
            raise SiteMaintenance(self.site)
        return resp

    async def get_text(self, path: str, *, params: dict[str, str] | None = None, cache: bool = False,
                       ajax: bool = False) -> str:
        """GET returning HTML. Optional in-memory cache for read-only pages (search)."""
        return await self._text("GET", path, params=params, cache=cache, ajax=ajax)

    async def post_text(self, path: str, *, params: dict[str, str] | None = None, cache: bool = False,
                        **kwargs: Any) -> str:
        """AJAX POST returning HTML (the site returns HTML fragments for many POSTs)."""
        return await self._text("POST", path, params=params, cache=cache, ajax=True, **kwargs)

    async def _text(self, method: str, path: str, *, params: dict[str, str] | None, cache: bool,
                    ajax: bool, **kwargs: Any) -> str:
        key = (method, path, repr(sorted((params or {}).items())))
        now = time.monotonic()
        if cache and key in self._cache and now - self._cache[key][0] < CACHE_TTL:
            return self._cache[key][1]
        resp = await self.request(method, path, params=params, ajax=ajax, **kwargs)
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, path)
        if cache:
            self._cache[key] = (now, resp.text)
        return resp.text

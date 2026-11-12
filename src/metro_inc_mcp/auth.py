"""Moi ID (Azure AD B2C) session handling.

The banner sites keep the OAuth tokens server side; the browser only holds JSESSIONID. The Moi ID SSO
cookies (*.moiid.ca) let `GET /b2c-login` complete without a form, which yields a new
authenticated JSESSIONID.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .client import GroceryClient
from .errors import AuthExpired, NotConfigured

log = logging.getLogger(__name__)

SSO_DOMAIN = "moiid.ca"
_AUTH_FLAG = re.compile(r"var isAuthenticated = (true|false);")


def page_is_authenticated(html: str) -> bool | None:
    """True / False from the page's JS global, None if the page does not say."""
    m = _AUTH_FLAG.search(html)
    return None if m is None else m.group(1) == "true"


def _is_sso(domain: str) -> bool:
    return domain.lstrip(".").endswith(SSO_DOMAIN)


class AuthManager:
    def __init__(self, client: GroceryClient, cookies_file: Path | None) -> None:
        self.client = client
        self.cookies_file = cookies_file
        self._loaded_mtime: int | None = None  # st_mtime_ns of the cookie file when it was last read or written
        self._authenticated = False
        self._lock = asyncio.Lock()

    # --- cookie file -------------------------------------------------------------------------

    def _read_file(self) -> tuple[Any, list[dict[str, Any]]]:
        if self.cookies_file is None:
            raise NotConfigured()
        try:
            raw = json.loads(self.cookies_file.read_text())
        except FileNotFoundError as e:
            raise NotConfigured(f"No Moi ID cookie file at {self.cookies_file}.") from e
        except json.JSONDecodeError as e:
            raise NotConfigured(f"METRO_COOKIES_FILE is not valid JSON: {self.cookies_file}") from e
        cookies = raw.get("cookies", []) if isinstance(raw, dict) else raw  # Playwright storageState or list
        if not isinstance(cookies, list):
            raise NotConfigured("METRO_COOKIES_FILE must be a JSON list of cookies or a Playwright storageState")
        return raw, cookies

    def _file_mtime(self) -> int | None:
        try:
            return self.cookies_file.stat().st_mtime_ns if self.cookies_file else None
        except OSError:
            return None

    def _load(self) -> None:
        """Load the Moi ID cookies into the session, again whenever the file changed since the last read.

        `metro-inc-mcp login` rewrites the file while servers are running: without the reload they would keep
        the expired SSO cookie in memory and report an expired session.
        """
        mtime = self._file_mtime()
        if self._loaded_mtime is not None and mtime == self._loaded_mtime:
            return
        _, cookies = self._read_file()
        jar = self.client.session.cookies
        for c in [c for c in jar.jar if _is_sso(c.domain)]:
            jar.delete(c.name, domain=c.domain, path=c.path)
        n = 0
        for c in cookies:
            domain = c.get("domain", "")
            if _is_sso(domain) and c.get("name") and c.get("value") is not None:
                jar.set(c["name"], c["value"], domain=domain, path=c.get("path", "/"), secure=c.get("secure", True))
                n += 1
        if n == 0:
            raise AuthExpired("The cookie file has no Moi ID (*.moiid.ca) cookies.")
        log.info("loaded %d Moi ID cookies", n)
        self._loaded_mtime = mtime

    def _save(self) -> None:
        """Write the (possibly rolled) Moi ID cookies back, keeping the file format. Atomic, mode 600."""
        if self.cookies_file is None:
            return
        raw, cookies = self._read_file()
        current = {(c.name, c.domain): c for c in self.client.session.cookies.jar if _is_sso(c.domain)}
        changed = False
        for c in cookies:
            fresh = current.get((c.get("name"), c.get("domain")))
            if fresh is not None and fresh.value != c.get("value"):
                c["value"] = fresh.value
                changed = True
        if not changed:
            return
        out = {**raw, "cookies": cookies} if isinstance(raw, dict) else cookies
        fd, tmp = tempfile.mkstemp(dir=self.cookies_file.parent, prefix=".cookies-")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(out, f, indent=1)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.cookies_file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        self._loaded_mtime = self._file_mtime()  # our own write: the jar already has these values
        log.info("Moi ID cookies refreshed in the cookie file")

    # --- session -----------------------------------------------------------------------------

    def mark_logged_out(self) -> None:
        self._authenticated = False

    async def ensure_logged_in(self) -> None:
        if self._authenticated:
            return
        async with self._lock:
            if not self._authenticated:
                await self._login()

    async def _login(self) -> None:
        self._load()
        jar = self.client.session.cookies
        for c in [c for c in jar.jar if not _is_sso(c.domain)]:
            jar.delete(c.name, domain=c.domain, path=c.path)
        settings = self.client.settings
        resp = await self.client.request("GET", settings.banner.login_path, allow_redirects=True)
        authenticated = page_is_authenticated(resp.text)
        if authenticated is None and SSO_DOMAIN not in resp.url:
            # The landing page may not carry the flag (e.g. a CMS home page): check on the cart page.
            authenticated = page_is_authenticated(await self.client.get_text(settings.write_paths.cart))
        if SSO_DOMAIN in resp.url or authenticated is not True:
            log.warning("silent login failed, ended on %s", resp.url.split("?")[0])
            raise AuthExpired()
        self._authenticated = True
        log.info("logged in to %s", self.client.base_url)
        try:
            self._save()
        except OSError as e:  # not fatal: the in-memory session works
            log.warning("could not update the cookie file: %s", e)

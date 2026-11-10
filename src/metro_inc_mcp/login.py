"""`metro-inc-mcp login`: open a browser, let the user log in to Moi ID, save the Moi ID cookies.

The user types the password and solves the reCAPTCHA in a visible browser; this module only waits for the
login to finish, then writes the *.moiid.ca cookies to the cookie file (Playwright storageState format,
atomic write, mode 600) and checks that a silent login works with them.

Needs Google Chrome and the optional extra `uv sync --extra login` (Playwright, only to read the cookies).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.request
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

from .config import BANNERS, DEFAULT_COOKIES_FILE, Settings, cookies_file_from_env

SSO_COOKIE_PREFIX = "x-ms-cpim-sso:"


def _is_sso(domain: str) -> bool:
    return domain.lstrip(".").endswith("moiid.ca")


def write_cookie_file(path: Path, cookies: list[dict]) -> None:
    """Write a storageState file with only the Moi ID cookies. Atomic, mode 600 (new directory: 700)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cookies-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"cookies": cookies, "origins": []}, f, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]


def _find_chrome() -> str:
    for candidate in [os.environ.get("METRO_CHROME"), *_CHROME_CANDIDATES]:
        if not candidate:
            continue
        found = candidate if os.path.isabs(candidate) and os.access(candidate, os.X_OK) else shutil.which(candidate)
        if found:
            return found
    sys.exit("Google Chrome not found. Install it, or set METRO_CHROME to the browser executable.")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tab_urls(port: int) -> list[str] | None:
    """URLs of the open tabs, from the DevTools HTTP endpoint (does not attach to the pages). None: browser gone."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            return [t.get("url", "") for t in json.load(r) if t.get("type") == "page"]
    except OSError:
        return None


async def _read_cookies(port: int) -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        sys.exit("Playwright is not installed. Run: uv sync --extra login")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        return [c for ctx in browser.contexts for c in await ctx.cookies()]


async def _browser_login(base_url: str, login_path: str, timeout: float) -> list[dict]:
    """Open a plain Chrome window (no automation flags, nothing attached), wait for the login, read the cookies.

    Cloudflare Turnstile on auth.moiid.ca fails (error 600010) in a browser driven by Playwright, so the
    browser runs on its own with a throwaway profile. Only the DevTools tab list is polled; Playwright
    attaches to read the cookies once the user is back on the site.
    """
    site_host = urlparse(base_url).hostname
    port = _free_port()
    with tempfile.TemporaryDirectory(prefix="metro-inc-mcp-login-") as profile:
        proc = await asyncio.create_subprocess_exec(
            _find_chrome(), f"--user-data-dir={profile}", f"--remote-debugging-port={port}",
            "--remote-allow-origins=http://127.0.0.1", "--no-first-run", "--no-default-browser-check",
            "--new-window", base_url + login_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        print("A Chrome window is open: log in to Moi ID there (password and captcha).", file=sys.stderr)
        try:
            seen_sso_page = False
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                await asyncio.sleep(1)
                urls = _tab_urls(port)
                if urls is None:
                    if proc.returncode is not None:
                        sys.exit("The browser was closed before the login finished.")
                    continue
                hosts = {urlparse(u).hostname or "" for u in urls}
                seen_sso_page |= any(_is_sso(h) for h in hosts)
                if seen_sso_page and site_host in hosts and not any(_is_sso(h) for h in hosts):
                    cookies = await _read_cookies(port)
                    if any(c["name"].startswith(SSO_COOKIE_PREFIX) and _is_sso(c["domain"]) for c in cookies):
                        return [c for c in cookies if _is_sso(c["domain"])]
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
    sys.exit(f"Login not finished after {int(timeout)} s.")


async def _check(settings: Settings) -> None:
    from .auth import AuthManager
    from .client import GroceryClient

    client = GroceryClient(settings)
    await AuthManager(client, settings.cookies_file).ensure_logged_in()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="metro-inc-mcp login",
        description="Open a browser, wait for you to log in to Moi ID, then save the Moi ID cookies.")
    parser.add_argument("--banner", default=os.environ.get("METRO_BANNER") or "superc", choices=sorted(BANNERS),
                        help="site to log in on (the Moi ID login works for every banner). Default: METRO_BANNER "
                             "or superc")
    parser.add_argument("--cookies-file", type=Path, default=cookies_file_from_env(),
                        help=f"where to save the Moi ID cookies. Default: METRO_COOKIES_FILE or {DEFAULT_COOKIES_FILE}")
    parser.add_argument("--timeout", type=float, default=600, help="seconds to wait for the login (default 600)")
    args = parser.parse_args(argv)

    os.environ["METRO_BANNER"] = args.banner
    path = args.cookies_file.expanduser()
    settings = replace(Settings.from_env(), cookies_file=path)
    banner = settings.banner
    cookies = asyncio.run(_browser_login(banner.base_url, banner.login_path, args.timeout))
    write_cookie_file(path, cookies)
    print(f"Saved {len(cookies)} Moi ID cookies to {path}", file=sys.stderr)
    try:
        asyncio.run(_check(settings))
    except Exception as e:  # noqa: BLE001 - report any failure of the check, the file is saved anyway
        sys.exit(f"The cookies were saved, but the silent login check failed: {e}")
    print(f"Silent login on {banner.base_url} works. The MCP servers will use the new cookies.", file=sys.stderr)

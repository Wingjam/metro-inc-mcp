"""Cookie file handling in AuthManager (offline: no request is sent)."""

from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest

from metro_inc_mcp.auth import AuthManager
from metro_inc_mcp.client import GroceryClient
from metro_inc_mcp.config import Settings
from metro_inc_mcp.errors import AuthExpired

SSO = "x-ms-cpim-sso:metroincb2c.onmicrosoft.com_0"


def write(path, sso_value, mtime_ns):
    cookies = [{"name": SSO, "value": sso_value, "domain": ".auth.moiid.ca", "path": "/"},
               {"name": "JSESSIONID", "value": "site", "domain": "www.superc.ca", "path": "/"}]
    path.write_text(json.dumps({"cookies": cookies, "origins": []}))
    os.utime(path, ns=(mtime_ns, mtime_ns))


def sso_values(client):
    return [c.value for c in client.session.cookies.jar if c.name == SSO]


@pytest.fixture
def auth(monkeypatch, tmp_path):
    monkeypatch.setenv("METRO_BANNER", "superc")
    path = tmp_path / "moiid-cookies.json"
    client = GroceryClient(replace(Settings.from_env(), cookies_file=path))
    return AuthManager(client, path), path, client


def test_loads_only_moiid_cookies(auth):
    manager, path, client = auth
    write(path, "first", 1_000_000_000)
    manager._load()
    assert sso_values(client) == ["first"]
    assert not [c for c in client.session.cookies.jar if c.name == "JSESSIONID"]


def test_reloads_when_the_file_changes(auth):
    # `metro-inc-mcp login` rewrites the file while a server runs: the next login must use the new cookies.
    manager, path, client = auth
    write(path, "old", 1_000_000_000)
    manager._load()
    manager._load()  # unchanged file: no reload
    assert sso_values(client) == ["old"]
    write(path, "new", 2_000_000_000)
    manager._load()
    assert sso_values(client) == ["new"]  # the old value is gone, not kept next to the new one


def test_no_moiid_cookie_is_an_expired_session(auth):
    manager, path, _ = auth
    path.write_text(json.dumps([{"name": "JSESSIONID", "value": "x", "domain": "www.superc.ca"}]))
    with pytest.raises(AuthExpired):
        manager._load()

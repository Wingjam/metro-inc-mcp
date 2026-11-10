from pathlib import Path

import pytest

from metro_inc_mcp.config import BANNERS, Settings
from metro_inc_mcp.parsing.products import parse_autocomplete


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ["METRO_BANNER", "METRO_LANGUAGE", "METRO_COOKIES_FILE"]:
        monkeypatch.delenv(name, raising=False)


def test_cookies_file_default(monkeypatch):
    monkeypatch.setenv("METRO_BANNER", "superc")
    assert Settings.from_env().cookies_file == Path.home() / ".metro-inc-mcp" / "moiid-cookies.json"
    monkeypatch.setenv("METRO_COOKIES_FILE", "")
    assert Settings.from_env().cookies_file == Path.home() / ".metro-inc-mcp" / "moiid-cookies.json"
    monkeypatch.setenv("METRO_COOKIES_FILE", "~/elsewhere/c.json")
    assert Settings.from_env().cookies_file == Path.home() / "elsewhere" / "c.json"


def test_banner_is_required():
    with pytest.raises(ValueError, match="METRO_BANNER"):
        Settings.from_env()


@pytest.mark.parametrize("raw", ["superc", "SuperC", "super-c", "SUPER_C"])
def test_banner_aliases(monkeypatch, raw):
    monkeypatch.setenv("METRO_BANNER", raw)
    assert Settings.from_env().banner.key == "superc"


@pytest.mark.parametrize(
    ("banner", "fr_search", "en_search", "write_cart"),
    [
        ("superc", "/recherche", "/en/search", "/mon-panier"),
        ("metro", "/epicerie-en-ligne/recherche", "/en/online-grocery/search", "/mon-panier"),
    ],
)
def test_bilingual_banners(monkeypatch, banner, fr_search, en_search, write_cart):
    monkeypatch.setenv("METRO_BANNER", banner)
    s = Settings.from_env()
    assert s.language == "fr"
    assert s.paths("fr").search == fr_search
    assert s.paths("en").search == en_search
    assert s.paths("en").search_page.format(page=2) == f"{en_search}-page-2"
    assert s.write_paths.cart == write_cart


def test_foodbasics_is_english_only(monkeypatch):
    monkeypatch.setenv("METRO_BANNER", "foodbasics")
    monkeypatch.setenv("METRO_LANGUAGE", "fr")
    s = Settings.from_env()
    assert s.language == "en"  # falls back to the only language
    assert s.resolve_language("fr") == "en"
    assert s.paths("fr").search == "/search"
    assert s.write_paths.cart == "/my-cart"


def test_every_banner_has_https_base_url():
    assert all(b.base_url.startswith("https://www.") for b in BANNERS.values())


@pytest.mark.parametrize(
    ("text", "total"),
    [("résultats (517)", 517), ("Search all results (511)", 511), ("Rechercher tous les résultats (1\u202f938)", 1938)],
)
def test_autocomplete_total_formats(text, total):
    assert parse_autocomplete(f"<html><body><a>{text}</a></body></html>", "https://www.metro.ca")[0] == total

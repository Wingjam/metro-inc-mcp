"""Jean Coutu (pharmacy banner): same platform, different paths, promo markup and pickup panel."""

from decimal import Decimal

import pytest

from metro_inc_mcp.config import Settings
from metro_inc_mcp.parsing.products import parse_autocomplete, parse_search_page
from metro_inc_mcp.parsing.service import (
    parse_pickup_days,
    parse_pickup_point,
    parse_store_list,
)

BASE = "https://www.jeancoutu.com"


def test_search(page):
    total, products = parse_search_page(page("jc-search-fr-shampooing.html"), BASE)
    assert total == 934
    assert len(products) == 42
    first = products[0]
    assert (first.code, first.brand, first.name, first.size) == ("661600004623", "Nutricap", "Shampooing sublime", "200 ml")
    assert first.price == Decimal("14.99")
    assert first.unit_price == "0,07 $ / ml"


def test_promo_without_regular_price(page):
    _, products = parse_search_page(page("jc-search-fr-shampooing.html"), BASE)
    on_sale = [p for p in products if p.on_sale]
    assert len(on_sale) == 12
    assert all(p.regular_price is None for p in on_sale)  # Jean Coutu shows only the promo price


def test_autocomplete_count_is_products(page):
    total, suggestions, products = parse_autocomplete(page("jc-autocomplete-fr-tylenol.html"), BASE)
    assert total == 98  # 'Produits (98)'
    assert suggestions == ["tylenol", "tylenol arthrite", "tylenol extra fort"]
    assert products[0].code == "062600960993"


def test_pickup_stores_exclude_delivery_entries(page):
    html = page("jc-service-timeslot-fr.html")
    stores = parse_store_list(html, pickup_only=True)
    assert [s.store_id for s in stores] == ["350", "381", "204", "250"]
    assert stores[0].address == "150, rue Sainte-Catherine Ouest, C.P. 181"
    assert len(parse_store_list(html)) > len(stores)  # delivery-only entries are left out
    assert parse_pickup_point(html, "350") == ("0350", "Odile Terzibachi")
    assert parse_pickup_point(html, "285") == (None, None)  # listed, but no pickup service point
    assert parse_pickup_days(html, "350") == []


@pytest.fixture
def jc(monkeypatch):
    monkeypatch.setenv("METRO_BANNER", "jeancoutu")
    monkeypatch.delenv("METRO_LANGUAGE", raising=False)
    return Settings.from_env()


def test_config(jc):
    assert jc.banner.kind == "pharmacy"
    assert jc.banner.pickup_timeslots is False
    assert jc.banner.login_path == "/magasiner/b2c-login"
    assert jc.paths("fr").search == "/magasiner/recherche"
    assert jc.paths("en").cart == "/en/shop/my-cart"
    assert jc.write_paths.service == "/magasiner/service-and-timeslot"

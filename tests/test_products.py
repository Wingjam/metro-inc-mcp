from decimal import Decimal

import pytest

from metro_inc_mcp.parsing.products import parse_autocomplete, parse_search_page

from .conftest import BASE_URL


def test_search_fr(page):
    total, products = parse_search_page(page("search-fr-lait.html"), BASE_URL)
    assert total == 737
    assert len(products) == 42
    assert all(p.price is not None for p in products)
    assert len({p.code for p in products}) == len(products)

    first = products[0]
    assert (first.code, first.brand, first.name, first.size) == ("055872026016", "Québon", "Lait 2 %", "4 L")
    assert first.price == Decimal("8.16")
    assert first.unit_price == "0,20 $ /100 ml"
    assert not first.on_sale
    assert first.url == f"{BASE_URL}/allees/produits-laitiers-et-oeufs/laits-cremes-et-beurres/laits-entiers-et-2/lait-2/p/055872026016"


def test_search_promo(page):
    _, products = parse_search_page(page("search-fr-lait.html"), BASE_URL)
    natrel = next(p for p in products if p.code == "064420010124")
    assert natrel.on_sale
    assert (natrel.price, natrel.regular_price) == (Decimal("4.99"), Decimal("5.49"))
    assert sum(p.on_sale for p in products) == 5


def test_search_en(page):
    total, products = parse_search_page(page("search-en-milk.html"), BASE_URL)
    assert total == 715
    assert len(products) == 42
    first = products[0]
    assert (first.code, first.name, first.price_text) == ("055872026016", "2% Milk", "$8.16 ea.")
    assert first.price == Decimal("8.16")
    assert first.unit_price == "$0.20 /100 ml"


@pytest.mark.parametrize("name", ["search-en-milk.html", "search-fr-empty.html"])
def test_search_skips_sponsored_tiles(page, name):
    html = page(name)
    assert "sponsoredTile" in html  # the fixture does contain ads
    _, products = parse_search_page(html, BASE_URL)
    assert all("sponsored" not in (p.url or "") for p in products)
    assert len(products) == html.count("default-product-tile") - html.count("sponsoredTile")


def test_search_empty(page):
    total, products = parse_search_page(page("search-fr-empty.html"), BASE_URL)
    assert total == 0
    assert products == []


@pytest.mark.parametrize(
    ("name", "total", "suggestions", "first_name", "price_text"),
    [
        ("autocomplete-fr-beurre.html", 520, ["beurre", "beurre à l'ail", "beurre arachide"], "Beurre salé", "6,19 $ ch."),
        ("autocomplete-en-butter.html", 472, ["butter", "peanut butter", "butter chicken"], "Salted Butter", "$6.19 ea."),
    ],
)
def test_autocomplete(page, name, total, suggestions, first_name, price_text):
    t, s, products = parse_autocomplete(page(name), BASE_URL)
    assert t == total
    assert s == suggestions
    assert len(products) == 3
    first = products[0]
    assert (first.code, first.name, first.brand) == ("059749894784", first_name, "Selection")
    assert first.price == Decimal("6.19")  # from data-main-price
    assert first.price_text == price_text

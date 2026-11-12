"""Favorites list parser (synthetic fixture, same markup as getFavorites) and favorites paths per banner."""

from decimal import Decimal

import pytest

from metro_inc_mcp.config import BANNERS
from metro_inc_mcp.parsing.products import parse_favorites

BASE = "https://www.superc.ca"


def test_parse_favorites(page):
    favorites = parse_favorites(page("favorites-fr.html"), BASE)
    assert [f.code for f in favorites] == ["4011", "055872026016", "059749894784"]
    banana, milk, butter = favorites
    assert (banana.name, banana.quantity, banana.is_weighted, banana.price, banana.available) == (
        "Banane", 6, True, Decimal("0.33"), True)
    assert (milk.brand, milk.size, milk.quantity, milk.price, milk.on_sale) == ("Québon", "4 L", 1, Decimal("8.16"), False)
    assert (butter.quantity, butter.available, butter.on_sale, butter.regular_price) == (2, False, True, Decimal("6.19"))
    assert milk.url == BASE + "/allees/produits-laitiers-et-oeufs/laits/lait-2/p/055872026016"


def test_empty_favorites():
    assert parse_favorites('<div class="cart-starter-preferences-empty">Aucun favori</div>', BASE) == []


@pytest.mark.parametrize(("banner", "lang", "prefix"), [
    ("superc", "fr", "/cart-starter"), ("superc", "en", "/en/cart-starter"),
    ("metro", "en", "/en/cart-starter"), ("foodbasics", "en", "/cart-starter"),
    ("jeancoutu", "fr", "/magasiner/cart-starter"), ("jeancoutu", "en", "/en/shop/cart-starter"),
])
def test_favorites_prefix(banner, lang, prefix):
    # From `var cartStarterUrl` on each site (2026-11-10).
    assert BANNERS[banner].paths[lang].favorites == prefix


@pytest.mark.parametrize(("banner", "lang", "path"), [
    ("superc", "fr", "/cart-starter/getFavorites"),
    ("jeancoutu", "fr", "/magasiner/mon-compte/mes-favoris"),  # no getFavorites on Jean Coutu (404)
    ("jeancoutu", "en", "/en/shop/my-account/my-favourites"),
])
def test_favorites_list_path(banner, lang, path):
    assert BANNERS[banner].paths[lang].favorites_list_path() == path

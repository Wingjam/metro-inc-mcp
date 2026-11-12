"""Product tiles from full search and autocomplete pages."""

from __future__ import annotations

import json
import re
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser, LexborNode

from ..models import Favorite, Product
from .prices import clean_text, parse_amount

_TOTAL_SEARCH = re.compile(r"(\d[\d\s\u00a0,]*)\s*(?:résultats?|results?)\b")
# 'résultats (517)', 'Search all results (511)', 'Rechercher tous les résultats (1\u202f938)'
# Jean Coutu: 'Produits (98)' / 'Products (98)'
_TOTAL_AUTOCOMPLETE = re.compile(r"(?:résultats?|results?|produits|products)\s*\((\d[\d\s\u00a0\u202f,]*)\)", re.IGNORECASE)
_SUGGESTIONS = re.compile(r"var autocompleteSuggestions = (\[.*?\]);", re.DOTALL)


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _text(node: LexborNode, selector: str) -> str | None:
    found = node.css_first(selector)
    return clean_text(found.text(separator=" ")) if found else None


def _classes(node: LexborNode, selector: str) -> list[str]:
    found = node.css_first(selector)
    return (found.attributes.get("class") or "").split() if found else []


def parse_tile(node: LexborNode, base_url: str) -> Product:
    a = node.attributes
    sale_text = _text(node, ".pricing__sale-price")
    before_text = _text(node, ".pricing__before-price")
    main_price = a.get("data-main-price")  # only on autocomplete tiles, dot decimal
    price = Decimal(main_price) if main_price else parse_amount(sale_text)
    link = node.css_first("a.product-details-link[href]") or node.css_first("a[href*='/p/']")
    href = link.attributes.get("href") if link else None
    return Product(
        code=a.get("data-product-code") or "",
        name=clean_text(a.get("data-product-name")) or "",
        brand=clean_text(a.get("data-product-brand")),
        size=_text(node, ".head__unit-details"),
        price=price,
        price_text=sale_text,
        regular_price=parse_amount(before_text) if before_text else None,
        # Jean Coutu marks promos with the promo-price class only, without a regular price.
        on_sale=before_text is not None or "promo-price" in _classes(node, ".pricing__sale-price"),
        unit_price=_text(node, ".pricing__secondary-price"),
        is_weighted=a.get("data-is-weighted") == "true",
        min_qty=_int(a.get("data-min-qty")),
        max_qty=_int(a.get("data-max-qty")),
        category=clean_text(a.get("data-product-category")),
        url=(base_url + href if href and href.startswith("/") else href),
    )


def _is_sponsored(node: LexborNode) -> bool:
    a = node.attributes
    return "sponsoredTile" in (a.get("class") or "").split() or "sponsored" in (a.get("data-source-name") or "")


def _tiles(tree: LexborHTMLParser, selector: str, base_url: str) -> list[Product]:
    """Organic product tiles, deduplicated. Sponsored (Criteo ad) tiles are skipped."""
    products, seen = [], set()
    for node in tree.css(selector):
        if not node.attributes.get("data-product-name") or _is_sponsored(node):
            continue
        p = parse_tile(node, base_url)
        if p.code and p.code not in seen:
            seen.add(p.code)
            products.append(p)
    return products


def parse_search_page(html: str, base_url: str) -> tuple[int | None, list[Product]]:
    tree = LexborHTMLParser(html)
    products = _tiles(tree, ".default-product-tile[data-product-code]", base_url)
    grid = tree.css_first("[data-total-results]")
    total = _int(grid.attributes.get("data-total-results")) if grid else None
    if total is None:
        m = _TOTAL_SEARCH.search(tree.body.text(separator=" ") if tree.body else html)
        total = int(re.sub(r"\D", "", m.group(1))) if m else None
    return total, products


def parse_favorites(html: str, base_url: str) -> list[Favorite]:
    """`<cart-starter>/getFavorites` fragment: one `.product-tile-cart-starter` (a default-product-tile) per favorite,
    grouped by aisle, with `data-qty` (saved quantity) and `data-is-inactive`. An empty list has no tile."""
    tree = LexborHTMLParser(html)
    favorites, seen = [], set()
    for node in tree.css(".product-tile-cart-starter[data-product-code]"):
        p = parse_tile(node, base_url)
        if not p.code or p.code in seen:
            continue
        seen.add(p.code)
        inactive = node.attributes.get("data-is-inactive")
        favorites.append(Favorite(**p.model_dump(), quantity=_int(node.attributes.get("data-qty")) or 1,
                                  available=None if inactive is None else inactive != "true"))
    return favorites


def parse_autocomplete(html: str, base_url: str) -> tuple[int | None, list[str], list[Product]]:
    tree = LexborHTMLParser(html)
    products = _tiles(tree, "[data-product-code][data-product-name]", base_url)
    m = _TOTAL_AUTOCOMPLETE.search(html)
    suggestions: list[str] = []
    s = _SUGGESTIONS.search(html)
    if s:
        try:
            suggestions = [str(x) for x in json.loads(s.group(1))]
        except json.JSONDecodeError:
            suggestions = []
    return (int(re.sub(r"\D", "", m.group(1))) if m else None), suggestions, products

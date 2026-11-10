"""The /mon-panier page: one div.product-card[data-cart-entry] per line, plus `var checkoutCartSummary = {...}`."""

from __future__ import annotations

import json
import re
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser, LexborNode

from ..errors import SiteChanged
from ..models import Cart, CartLine, PriceLine
from .prices import clean_text, is_approximate, parse_amount

_SUMMARY = re.compile(r"var checkoutCartSummary = (\{.*?\});\s*$", re.DOTALL | re.MULTILINE)


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def _text(node: LexborNode, selector: str) -> str | None:
    found = node.css_first(selector)
    return clean_text(found.text(separator=" ")) if found else None


def _cents(value: object) -> Decimal | None:
    return (Decimal(value) / 100) if isinstance(value, int) else None


def _amount(price_line: dict) -> Decimal | None:
    """`value` in cents (grocery banners), else the formatted text (Jean Coutu has no `value`; '-' gives None)."""
    cents = _cents(price_line.get("value"))
    return cents if cents is not None else parse_amount(clean_text(price_line.get("formattedPrice")))


def parse_line(card: LexborNode) -> CartLine:
    a = card.attributes
    price_node = card.css_first(".price-update")
    price_text = clean_text(price_node.text(separator=" ")) if price_node else None
    toggle = card.css_first("input[type=checkbox][name*=toggle-switch]")
    return CartLine(
        entry_number=_int(a.get("data-cart-entry")) or 0,
        code=a.get("data-product-code") or "",
        name=_text(card, ".head__title") or clean_text(a.get("data-product-name")) or "",
        brand=_text(card, ".head__brand"),
        size=_text(card, ".head__unit-details"),
        quantity=_int(a.get("data-qty")) or 0,
        price=parse_amount(price_text),
        price_text=price_text,
        on_sale="pi-price-promo" in ((price_node.attributes.get("class") or "") if price_node else ""),
        line_total=parse_amount(_text(card, ".subtotal-value")),
        approximate=a.get("data-is-weighted") == "true" or is_approximate(price_text),
        substitution_allowed=("checked" in toggle.attributes) if toggle else None,
        max_qty=_int(a.get("data-max-qty")),
        # "Rupture de stock" lines carry data-is-inactive="true" (verified on Jean Coutu 2026-11-08).
        available=None if a.get("data-is-inactive") is None else a.get("data-is-inactive") != "true",
    )


def parse_csrf(html: str) -> dict[str, str]:
    """CSRF header for calls that need one, from <meta name="_csrf" content="<uuid>"> and
    <meta name="_csrf_header" content="X-CSRF-TOKEN">. Metro has them; Super C and Jean Coutu do not ({})."""
    tree = LexborHTMLParser(html)
    token = tree.css_first('meta[name="_csrf"]')
    value = token.attributes.get("content") if token else None
    if not value:
        return {}
    header = tree.css_first('meta[name="_csrf_header"]')
    return {(header.attributes.get("content") if header else None) or "X-CSRF-TOKEN": value}


def parse_cart_page(html: str, language: str = "fr") -> Cart:
    tree = LexborHTMLParser(html)
    lines: dict[int, CartLine] = {}
    for card in tree.css(".product-card[data-cart-entry]"):
        line = parse_line(card)
        lines.setdefault(line.entry_number, line)  # entries can be repeated for other layouts

    summary: dict = {}
    m = _SUMMARY.search(html)
    if m:
        try:
            summary = json.loads(m.group(1))
        except json.JSONDecodeError as e:
            raise SiteChanged("cart summary JSON") from e
    elif lines:
        raise SiteChanged("cart summary (checkoutCartSummary) not found")

    price_lines = [
        PriceLine(description=clean_text(p.get("description")) or "", amount=_amount(p),
                  text=clean_text(p.get("formattedPrice")))
        for p in summary.get("priceLines") or []
    ]
    subtotal = next((p.amount for p in price_lines
                     if re.sub(r"\W", "", p.description.lower()).startswith(("soustotal", "subtotal"))), None)
    if subtotal is None and price_lines:
        subtotal = price_lines[0].amount  # first line is the subtotal in both languages
    big = summary.get("bigTotalPriceLine") or summary.get("totalPriceLine") or {}
    return Cart(
        language=language,
        item_count=summary.get("cartNbItems", sum(line.quantity for line in lines.values())),
        lines=[lines[k] for k in sorted(lines)],
        subtotal=subtotal,
        estimated_total=_amount(big),
        price_lines=price_lines,
        minimum_order_reached=summary.get("minimumOrderAmountExceeded"),
    )

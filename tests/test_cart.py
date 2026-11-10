"""Cart parser tests. The cart fixtures are synthetic (hand-made, same markup as the site)."""

from decimal import Decimal

import pytest

from metro_inc_mcp.auth import page_is_authenticated
from metro_inc_mcp.errors import SiteChanged
from metro_inc_mcp.parsing.cart import parse_cart_page
from metro_inc_mcp.parsing.service import parse_service_context


@pytest.mark.parametrize(
    ("lang", "subtotal_label", "first_name", "first_price_text"),
    [("fr", "Sous-total*", "Lait 2 %", "8,16 $"), ("en", "Subtotal*", "2% Milk", "$8.16")],
)
def test_cart_totals(page, lang, subtotal_label, first_name, first_price_text):
    cart = parse_cart_page(page(f"cart-{lang}.html"), lang)
    assert cart.language == lang
    assert cart.item_count == 10
    assert len(cart.lines) == 4
    assert cart.subtotal == cart.estimated_total == Decimal("27.51")
    assert sum(line.line_total for line in cart.lines) == cart.subtotal
    assert cart.price_lines[0].description == subtotal_label
    assert cart.minimum_order_reached is False

    first = cart.lines[0]
    assert (first.entry_number, first.code, first.name, first.brand, first.size) == (
        0, "055872026016", first_name, "Québon", "4 L")
    assert first.price_text == first_price_text
    assert not first.on_sale and first.substitution_allowed


def test_cart_entry_numbers_keep_gaps(page):
    cart = parse_cart_page(page("cart-fr.html"))
    assert [line.entry_number for line in cart.lines] == [0, 1, 2, 4]  # deleted entries are not renumbered


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_cart_quantities_promo_and_weighted(page, lang):
    by_code = {line.code: line for line in parse_cart_page(page(f"cart-{lang}.html"), lang).lines}
    butter = by_code["059749894784"]
    assert (butter.quantity, butter.price, butter.line_total) == (2, Decimal("6.19"), Decimal("12.38"))
    assert by_code["064420010124"].on_sale
    banana = by_code["4011"]
    assert (banana.quantity, banana.price, banana.approximate, banana.brand) == (6, Decimal("0.33"), True, None)
    assert banana.substitution_allowed is False
    assert {c for c, line in by_code.items() if line.approximate} == {"4011"}


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_cart_service_context(page, lang):
    html = page(f"cart-{lang}.html")
    assert page_is_authenticated(html) is True
    ctx = parse_service_context(html)
    assert ctx is not None
    assert (ctx.service_type, ctx.store_id, ctx.store_name) == ("PICK_UP_IN_STORE", "262", "Super C Drummondville")
    assert ctx.timeslot_selected is False


def test_empty_cart_page():
    cart = parse_cart_page("<html><body><script>var isAuthenticated = true;</script></body></html>")
    assert cart.lines == []
    assert cart.subtotal is None


def test_cart_without_summary_is_site_change(page):
    html = page("cart-fr.html").replace("var checkoutCartSummary", "var somethingElse")
    with pytest.raises(SiteChanged):
        parse_cart_page(html)


def test_page_is_authenticated():
    assert page_is_authenticated("var isAuthenticated = false;") is False
    assert page_is_authenticated("<html></html>") is None

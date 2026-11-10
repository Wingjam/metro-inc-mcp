from decimal import Decimal

import pytest

from metro_inc_mcp.cart import InvalidProductCode, _check_code
from metro_inc_mcp.parsing.service import (
    parse_form_state,
    parse_pickup_days,
    parse_pickup_point,
    parse_store_list,
)
from metro_inc_mcp.service_context import (
    InvalidInput,
    _check_store_id,
    normalize_postal_code,
)

STORES = [
    ("274", "Super C Victoriaville"),
    ("6167", "Super C St-Nicéphore"),
    ("262", "Super C Drummondville"),
    ("4888", "Super C Thetford Mines"),
]


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_store_list(page, lang):
    stores = parse_store_list(page(f"service-choice-{lang}.html"))
    assert [(s.store_id, s.name) for s in stores] == STORES
    assert stores[0].address == "601, Rue Jutras Est"


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_pickup_point_and_form_state(page, lang):
    html = page(f"service-timeslot-{lang}.html")
    assert parse_pickup_point(html, "274") == ("0000000429", "Super C Victoriaville")
    assert parse_pickup_point(html, "6167") == ("0000000932", "Super C St-Nicéphore")
    assert parse_pickup_point(html, "9999") == (None, None)
    assert parse_form_state(html)


@pytest.mark.parametrize(
    ("lang", "today", "tomorrow", "slot_label", "price_text"),
    [("fr", "Aujourd'hui", "Demain", "12h-13h", "Gratuit"), ("en", "Today", "Tomorrow", "12PM-1PM", "Free")],
)
def test_pickup_days(page, lang, today, tomorrow, slot_label, price_text):
    days = parse_pickup_days(page(f"service-timeslot-{lang}.html"), "274")
    assert len(days) == 14
    assert [d.date for d in days] == sorted(d.date for d in days)
    assert (days[0].date, days[0].label, days[0].status, days[0].slots) == ("2026-11-08", today, "FULL", [])
    assert (days[1].label, days[1].status, len(days[1].slots)) == (tomorrow, "AVAILABLE", 9)
    assert [len(d.slots) for d in days[1:4]] == [9, 12, 12]
    assert all(d.status == "NO_TIMESLOT" and not d.slots for d in days[4:])

    slot = days[1].slots[0]
    assert (slot.slot_id, slot.start, slot.end) == ("15683441", "2026-11-09T12:00-05:00", "2026-11-09T13:00-05:00")
    assert (slot.label, slot.price, slot.price_text, slot.available) == (slot_label, Decimal(0), price_text, True)
    assert all(s.start.startswith(d.date) for d in days for s in d.slots)


def test_pickup_days_other_store_has_no_slots(page):
    days = parse_pickup_days(page("service-timeslot-fr.html"), "6167")
    assert all(not d.slots for d in days)


@pytest.mark.parametrize(("value", "expected"), [("G6P 7H4", "G6P 7H4"), ("g6p7h4", "G6P 7H4"), (" g6p-7h4 ", "G6P 7H4")])
def test_normalize_postal_code(value, expected):
    assert normalize_postal_code(value) == expected


@pytest.mark.parametrize("value", ["12345", "G6P", "", "G6P 7H4 1"])
def test_normalize_postal_code_rejects(value):
    with pytest.raises(InvalidInput):
        normalize_postal_code(value)


def test_store_id_validation():
    assert _check_store_id(" 274 ") == "274"
    for bad in ["27a", "", "274; drop", "123456789"]:
        with pytest.raises(InvalidInput):
            _check_store_id(bad)


def test_product_code_validation():
    assert _check_code(" 4011 ") == "4011"
    assert _check_code("055872026016") == "055872026016"
    for bad in ["abc", "", "4011/../x", "123456789012345"]:
        with pytest.raises(InvalidProductCode):
            _check_code(bad)

from decimal import Decimal

import pytest

from metro_inc_mcp.parsing.prices import clean_text, is_approximate, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("8,16 $ch.", "8.16"),
        ("0,49 $ env. ch.", "0.49"),
        ("Prix régulier5,49 $ch.", "5.49"),
        ("1 250,00 $", "1250.00"),
        ("1\u00a0250,00 $", "1250.00"),
        ("16,51 $ / kg 7,49 $ / lb", "16.51"),
        ("$8.16ea.", "8.16"),
        ("$0.49 approx. ea.", "0.49"),
        ("Regular price$5.49 ea.", "5.49"),
        ("$1,250.00", "1250.00"),
        ("$16.51 / kg $7.49 / lb", "16.51"),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", [None, "", "Gratuit", "Free", "6x156 mL", "-"])
def test_parse_amount_none(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0,49 $ env. ch.", True), ("$0.49 approx. ea.", True), ("8,16 $ch.", False), ("$8.16 ea.", False), (None, False)],
)
def test_is_approximate(text, expected):
    assert is_approximate(text) is expected


def test_clean_text():
    assert clean_text("  Lait\n  2 %  ") == "Lait 2 %"
    assert clean_text("   ") is None
    assert clean_text(None) is None

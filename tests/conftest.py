"""Offline parser tests.

Search, autocomplete and service panel fixtures are anonymous superc.ca pages captured on
2026-11-08, trimmed and stripped of ad / analytics ids. The cart fixtures are synthetic
(hand-made with the same markup as the site), so no real account data is stored.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BASE_URL = "https://www.superc.ca"


@pytest.fixture
def page():
    def read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return read

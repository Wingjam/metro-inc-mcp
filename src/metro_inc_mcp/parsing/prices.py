"""Price formats on the Metro inc. banner sites (superc.ca, metro.ca, foodbasics.ca).

French: '8,16 $ch.', '0,49 $ env. ch.', 'Prix régulier5,49 $ch.', '1 250,00 $'.
English: '$8.16ea.', '$0.49 approx. ea.', 'Regular price$5.49 ea.', '$1,250.00'.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SPACES = r"[\s\u00a0\u202f]"
_FR = re.compile(rf"(\d{{1,3}}(?:{_SPACES}\d{{3}})+|\d+),(\d{{2}})")
_EN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})")
_APPROX = re.compile(r"\b(env|approx)\b\.?", re.IGNORECASE)


def parse_amount(text: str | None) -> Decimal | None:
    """First amount in the text, French (comma decimal) or English (dot decimal) format."""
    if not text:
        return None
    candidates = [m for m in (_FR.search(text), _EN.search(text)) if m]
    if not candidates:
        return None
    m = min(candidates, key=lambda x: (x.start(), -(x.end() - x.start())))  # earliest, then longest
    whole = re.sub(rf"{_SPACES}|,", "", m.group(1))
    try:
        return Decimal(f"{whole}.{m.group(2)}")
    except InvalidOperation:
        return None


def is_approximate(text: str | None) -> bool:
    """'env.' (fr) or 'approx.' (en) marks a price that depends on the weight."""
    return bool(text and _APPROX.search(text))


def clean_text(text: str | None) -> str | None:
    """Collapse whitespace; None for empty strings."""
    if text is None:
        return None
    out = re.sub(r"\s+", " ", text).strip()
    return out or None

"""Deterministic parsing of guided timing ("1H 2027", "mid-2027", "PDUFA date of March 15, 2027").

The models return the sponsor's own words (`timing_text`); this module turns them into a window.
Two extractors agree on timing when their texts parse to the same window, which is far more stable
than comparing model-computed dates.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9

Window = tuple[date, date, str]  # start, end, precision


def _end_of_month(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def _q(y: int, q: int) -> Window:
    return date(y, 3 * q - 2, 1), _end_of_month(y, 3 * q), "quarter"


def _year_from(text: str, statement_date: date) -> int | None:
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(?:[1-4]q|q[1-4]|[12]h|h[12])\s?(\d{2})\b", text) or re.search(
        r"(?:fy|'|’)\s?(\d{2})\b", text
    )
    if m:
        return 2000 + int(m.group(1))
    if re.search(r"\b(this year|current year)\b", text):
        return statement_date.year
    if re.search(r"\bnext year\b", text):
        return statement_date.year + 1
    return None


def parse_timing(text: str | None, statement_date: date) -> Window | None:
    if not text:
        return None
    t = " ".join(text.lower().replace("–", "-").replace("—", "-").split())

    # Exact day: "March 15, 2027", "15 March 2027", "2027-03-15"
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if m:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, d, "day"
    m = re.search(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b", t)
    if m and m.group(1) in MONTHS:
        d = date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        return d, d, "day"
    m = re.search(r"\b(\d{1,2})\s+([a-z]{3,9})\.?\s+(20\d{2})\b", t)
    if m and m.group(2) in MONTHS:
        d = date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        return d, d, "day"

    y = _year_from(t, statement_date)
    if y is None:
        return None

    # Quarters: "Q1 2027", "first quarter of 2027", "1Q27"
    m = re.search(
        r"\bq([1-4])(?=\b|\s?\d{2}\b)|\b([1-4])q(?=\b|\s?\d{2}\b)|\b(first|second|third|fourth)\s+quarter\b",
        t,
    )
    if m:
        q = (
            int(m.group(1) or m.group(2) or 0)
            or ["first", "second", "third", "fourth"].index(m.group(3)) + 1
        )
        return _q(y, q)
    # Halves: "1H 2027", "H2 2027", "first half", "second half"
    m = re.search(r"\b(?:h([12])|([12])h)(?=\b|\s?\d{2}\b)|\b(first|second)\s+half\b", t)
    if m:
        h = int(m.group(1) or m.group(2) or 0) or (1 if m.group(3) == "first" else 2)
        return (
            (date(y, 1, 1), date(y, 6, 30), "half")
            if h == 1
            else (date(y, 7, 1), date(y, 12, 31), "half")
        )
    # Seasonal / positional words
    if re.search(r"\b(early)\b", t):
        return date(y, 1, 1), date(y, 4, 30), "range"
    if re.search(r"\b(mid|middle)\b", t):
        return date(y, 5, 1), date(y, 8, 31), "range"
    if re.search(r"\b(late|end of|year-end|year end|by the end)\b", t):
        start = date(y, 9, 1)
        if re.search(r"\bby (the )?(end|year-end)\b", t):
            start = max(statement_date, date(y, 1, 1))
        return start, date(y, 12, 31), "range"
    # Month + year: "March 2027"
    m = re.search(r"\b([a-z]{3,9})\.?\s+(20\d{2})\b", t)
    if m and m.group(1) in MONTHS:
        mo = MONTHS[m.group(1)]
        return date(y, mo, 1), _end_of_month(y, mo), "month"
    # Bare year: "in 2027", "during 2027"
    if re.fullmatch(r".*\b(in|during|by|for)?\s*20\d{2}\b.*", t):
        if re.search(r"\bby\b", t):
            return max(statement_date, date(y, 1, 1)), date(y, 12, 31), "range"
        return date(y, 1, 1), date(y, 12, 31), "year"
    return None


def iso_or_none(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None

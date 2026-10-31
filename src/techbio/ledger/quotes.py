"""Quote verification for extracted statements (operator decision 2026-10-30).

Every statement an extractor (or the tie-breaker) returns carries a quote, checked against the full
source text:

- exact: present verbatim, modulo whitespace, curly quotes, dashes and case;
- fuzzy: the best-aligned source span scores >= QUOTE_MATCH_THRESHOLD (normalized Indel similarity,
  rapidfuzz partial_ratio), every identifier-like token of the quote (anything with a digit or two
  capitals: EXT-202, SUMMIT, 2027, 2b) occurs at that place in the source, and the quote and the span
  agree on negation. The score alone would accept "met its primary endpoint" against "did not meet
  its primary endpoint" (0.86), or EXT-303 against EXT-202;
- otherwise rejected: the statement is dropped, and the check is logged with the model's claimed
  quote and the nearest source span so that drops can be spot-checked.

Quotes shorter than MIN_FUZZY_CHARS must be exact: there is too little text to judge a near match.
Every check (accepted or not) is written to `quote_checks`, which stays local: spans are source text.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import Connection, Engine, select

from techbio.core.db import now, quote_checks, sources
from techbio.core.ids import new_id

MATCHER_VERSION = "quotes_v1"
QUOTE_MATCH_THRESHOLD = 0.8
MIN_CHARS = 12
MIN_FUZZY_CHARS = 30
IDENTIFIER_MARGIN = 15  # characters either side of the span searched for the quote's identifiers

_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "\xa0": " ",
    }
)
_TOKEN = re.compile(r"\w+(?:['\-./]\w+)*")
NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "neither",
        "nor",
        "without",
        "fail",
        "fails",
        "failed",
        "unable",
        "cannot",
        "can't",
        "didn't",
        "doesn't",
        "don't",
        "won't",
        "isn't",
        "wasn't",
        "aren't",
        "weren't",
    }
)


@dataclass(frozen=True)
class QuoteMatch:
    accepted: bool
    method: str  # exact | fuzzy | rejected
    score: float
    span: str | None  # nearest source span, in the source's own wording
    reject_reason: str | None = None


def _norm(s: str) -> str:
    return " ".join(s.translate(_MAP).split())


def _fold(s: str) -> str:
    # Lowercase without changing the length, so offsets in the folded text index the original.
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in s)


def _tokens(s: str) -> list[str]:
    return _TOKEN.findall(s)


def _identifiers(s: str) -> set[str]:
    return {
        _fold(t)
        for t in _tokens(s)
        if any(c.isdigit() for c in t) or sum(c.isupper() for c in t) >= 2
    }


def _negated(s: str) -> bool:
    return any(_fold(t) in NEGATIONS for t in _tokens(s))


def _widen(text: str, start: int, end: int) -> tuple[int, int]:
    """Extend [start, end) to whole words."""
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return start, end


def match_quote(
    quote: str | None, text: str, threshold: float = QUOTE_MATCH_THRESHOLD
) -> QuoteMatch:
    if not quote or not quote.strip():
        return QuoteMatch(False, "rejected", 0.0, None, "missing")
    q = _norm(quote).strip(" .\"'")
    if len(q) < MIN_CHARS:
        return QuoteMatch(False, "rejected", 0.0, None, "too_short")
    t = _norm(text)
    qf, tf = _fold(q), _fold(t)
    i = tf.find(qf)
    if i >= 0:
        return QuoteMatch(True, "exact", 1.0, t[i : i + len(q)])
    if len(qf) > len(tf):
        return QuoteMatch(False, "rejected", 0.0, None, "below_threshold")
    a = fuzz.partial_ratio_alignment(qf, tf)
    score = round(a.score / 100, 4)
    start, end = _widen(t, a.dest_start, a.dest_end)
    span = t[start:end].strip()
    if len(q) < MIN_FUZZY_CHARS:
        return QuoteMatch(False, "rejected", score, span, "too_short_for_fuzzy")
    if score < threshold:
        return QuoteMatch(False, "rejected", score, span, "below_threshold")
    lo, hi = _widen(t, max(0, start - IDENTIFIER_MARGIN), min(len(t), end + IDENTIFIER_MARGIN))
    if not _identifiers(q) <= {_fold(x) for x in _tokens(t[lo:hi])}:
        return QuoteMatch(False, "rejected", score, span, "identifier_mismatch")
    if _negated(q) != _negated(span):
        return QuoteMatch(False, "rejected", score, span, "negation_mismatch")
    return QuoteMatch(True, "fuzzy", score, span)


def record_check(
    conn: Connection,
    m: QuoteMatch,
    *,
    run_id: str,
    source_id: str,
    model_key: str,
    role: str,
    claimed_quote: str | None,
    statement_idx: int | None = None,
    field: str | None = None,
    statement: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        quote_checks.insert().values(
            check_id=new_id("qc"),
            run_id=run_id,
            source_id=source_id,
            model_key=model_key,
            role=role,
            statement_idx=statement_idx,
            field=field,
            statement=statement,
            claimed_quote=claimed_quote,
            matched_span=m.span,
            score=m.score,
            method=m.method,
            accepted=m.accepted,
            reject_reason=m.reject_reason,
            threshold=QUOTE_MATCH_THRESHOLD,
            matcher_version=MATCHER_VERSION,
            created_recorded_at=now(),
        )
    )


def drop_sample(
    engine: Engine, n: int = 10, days: int = 7, today: date | None = None
) -> list[dict[str, Any]]:
    """A random sample of extractor drops from the last `days` days, for the operator's spot-check.
    Seeded by the date, so the same day's summary shows the same sample. Local only: never exported
    (the claimed quote and the span are document text)."""
    today = today or datetime.now(UTC).date()
    since = datetime.combine(today - timedelta(days=days), datetime.min.time(), UTC)
    q = (
        select(quote_checks, sources.c.url, sources.c.title)
        .join(sources, sources.c.source_id == quote_checks.c.source_id)
        .where(
            quote_checks.c.accepted.is_(False),
            quote_checks.c.role == "extractor",
            quote_checks.c.created_recorded_at >= since,
        )
        .order_by(quote_checks.c.check_id)
    )
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(q).mappings()]
    rng = random.Random(today.isoformat())
    picked = rng.sample(rows, min(n, len(rows)))
    return [
        {
            "check_id": r["check_id"],
            "url": r["url"],
            "title": r["title"],
            "model_key": r["model_key"],
            "reject_reason": r["reject_reason"],
            "score": r["score"],
            "claimed_quote": r["claimed_quote"],
            "nearest_span": r["matched_span"],
            "statement": r["statement"],
        }
        for r in picked
    ]

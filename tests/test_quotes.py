"""Quote verification (operator decision 2026-10-30): near-verbatim quotes are kept, drops are logged.

A fuzzy score alone would accept a quote whose meaning is flipped (negation) or whose identifiers
(asset code, trial, number, date) differ from the source, because those are a few characters in a long
sentence. The guards below are part of the rule, not tuning.
"""

import pytest

from techbio.ledger.quotes import QUOTE_MATCH_THRESHOLD, match_quote

SOURCE = (
    "Example Therapeutics, Inc. (Nasdaq: EXTX) today announced that the Phase 3 HORIZON-2 trial of "
    "zorbalimab did not meet its primary endpoint of EASI-75 at week 16. The Company remains on "
    "track to report topline results from the Phase 2b SUMMIT trial of EXT-202 in mid-2027, and "
    "expects to submit a Biologics License Application in the second half of 2028."
)


def test_threshold_is_the_operator_value():
    assert QUOTE_MATCH_THRESHOLD == 0.8


def test_exact_quote_modulo_whitespace_and_typography():
    source = SOURCE.replace("its primary", 'its "primary"')
    m = match_quote("HORIZON-2  trial of zorbalimab did not meet its “primary” endpoint", source)
    assert m.accepted and m.method == "exact" and m.score == 1.0


def test_near_verbatim_quote_is_kept_with_its_source_span():
    # The model changed "remains" to "is": a near-verbatim quote.
    m = match_quote(
        "The Company is on track to report topline results from the Phase 2b SUMMIT trial of "
        "EXT-202 in mid-2027",
        SOURCE,
    )
    assert m.accepted and m.method == "fuzzy" and QUOTE_MATCH_THRESHOLD <= m.score < 1.0
    # The span is cut from the source on word boundaries, so a reviewer sees the real wording.
    assert m.span.startswith("The Company remains on track") and m.span in SOURCE


def test_negation_flip_is_dropped_even_with_a_high_score():
    m = match_quote("the Phase 3 HORIZON-2 trial of zorbalimab met its primary endpoint", SOURCE)
    assert m.score >= QUOTE_MATCH_THRESHOLD  # the score alone would have accepted it
    assert not m.accepted and m.reject_reason == "negation_mismatch"


@pytest.mark.parametrize(
    "quote",
    [
        # Asset code changed.
        "on track to report topline results from the Phase 2b SUMMIT trial of EXT-303 in mid-2027",
        # Year changed.
        "on track to report topline results from the Phase 2b SUMMIT trial of EXT-202 in mid-2028",
        # Trial name changed.
        "on track to report topline results from the Phase 2b SUNRISE trial of EXT-202 in mid-2027",
    ],
)
def test_changed_identifier_is_dropped(quote):
    m = match_quote(quote, SOURCE)
    assert not m.accepted and m.reject_reason == "identifier_mismatch"
    assert m.span  # the nearest span is still logged for the spot-check


def test_unrelated_sentence_is_dropped_below_threshold():
    m = match_quote("Enrollment in the open-label extension was completed ahead of plan.", SOURCE)
    assert not m.accepted and m.reject_reason == "below_threshold" and m.score < 0.8


def test_short_quotes_must_be_exact():
    assert match_quote("did not meet its primary", SOURCE).accepted  # exact, 24 chars
    m = match_quote("did not met its primary", SOURCE)  # near, but too short to judge fuzzily
    assert not m.accepted and m.reject_reason == "too_short_for_fuzzy"
    assert match_quote("SUMMIT", SOURCE).reject_reason == "too_short"
    assert match_quote(None, SOURCE).reject_reason == "missing"

import pytest

from techbio.ledger.taxonomy import (
    DATA_TRIGGERS,
    EXPLANATIONS,
    exclusion_for,
    explanation_category,
    score_outcome,
)


@pytest.mark.parametrize(
    ("event_type", "result", "subtype", "expl", "binary", "void"),
    [
        ("readout", "met", None, None, 1, None),
        ("readout", "missed", None, "efficacy", 0, None),
        ("readout", "mixed", None, None, 0, None),
        ("readout", "stopped", "efficacy", None, 1, None),
        ("readout", "stopped", "futility", None, 0, None),
        ("readout", "stopped", "safety", None, 0, None),
        ("readout", "stopped", "business", "financial", None, "stopped_business"),
        (
            "readout",
            "stopped",
            "operational",
            "enrollment_operational",
            None,
            "stopped_operational",
        ),
        ("fda_decision", "approved", None, None, 1, None),
        ("fda_decision", "CRL", None, "manufacturing_cmc", 0, None),
        ("fda_decision", "withdrawn", None, "regulatory_feedback", 0, None),
        ("fda_decision", "withdrawn", None, "not_disclosed", 0, None),
        (
            "fda_decision",
            "withdrawn",
            None,
            "strategic_portfolio",
            None,
            "withdrawn_strategic_portfolio",
        ),
        ("adcom", "favorable", None, None, 1, None),
        ("adcom", "unfavorable", None, None, 0, None),
        ("adcom", "split", None, None, 0, None),
    ],
)
def test_void_rule(event_type, result, subtype, expl, binary, void):
    """S16: voided only if cancelled or stopped for reasons unrelated to the outcome; data is scored."""
    o = score_outcome(event_type, result, subtype, expl)
    assert (o.binary, o.void_reason) == (binary, void)


def test_cancelled_and_no_vote_are_void():
    assert score_outcome("adcom", "", cancelled=True).void_reason == "cancelled"
    assert score_outcome("adcom", "favorable", adcom_vote_held=False).void_reason == "adcom_no_vote"


def test_discontinuations_are_ledger_only():
    assert score_outcome("discontinuation", "discontinued").binary is None


def test_invalid_combinations_raise():
    with pytest.raises(ValueError):
        score_outcome("readout", "approved")
    with pytest.raises(ValueError):
        score_outcome("readout", "stopped")


# ---- operator decisions of 2026-10-30 (second round), with the registry records that prompted them


@pytest.mark.parametrize("trigger", DATA_TRIGGERS)
def test_business_stop_with_a_documented_data_trigger_scores_as_missed(trigger):
    o = score_outcome("readout", "stopped", "business", "strategic_portfolio", data_trigger=trigger)
    assert (o.binary, o.void_reason, o.scored_as) == (0, None, "missed")


def test_business_stop_without_a_data_trigger_is_void():
    # NCT04396236 (Lilly, Phase 3, 847 enrolled): "Study terminated due to strategic business decision"
    o = score_outcome("readout", "stopped", "business", "strategic_portfolio")
    assert (o.binary, o.void_reason, o.scored_as) == (None, "stopped_business", None)


def test_failure_to_enroll_is_void_operational():
    # NCT05074420 (Lilly, Phase 3, 6 enrolled): "inability to enroll participants"
    o = score_outcome("readout", "stopped", "operational", "enrollment_operational")
    assert o.void_reason == "stopped_operational"
    # A data trigger does not turn an operational stop into a scored one.
    o = score_outcome("readout", "stopped", "operational", None, data_trigger="interim_analysis")
    assert o.void_reason == "stopped_operational"


def test_every_business_stop_is_logged_as_strategic_stop_after_enrollment():
    for stated in ("strategic_portfolio", "financial", "not_disclosed", None):
        assert (
            explanation_category("readout", "stopped", "business", stated)
            == "strategic_stop_after_enrollment"
        )
    assert explanation_category("readout", "stopped", "futility", "efficacy") == "efficacy"
    assert explanation_category("readout", "missed", None, "efficacy") == "efficacy"
    # Withdrawn applications keep their own categories (the void rule for those is unchanged).
    assert explanation_category("fda_decision", "withdrawn", None, "financial") == "financial"
    # The derived category is never offered to the extractors.
    assert "strategic_stop_after_enrollment" not in EXPLANATIONS


def test_scored_as_is_the_result_for_ordinary_outcomes():
    assert score_outcome("readout", "met").scored_as == "met"
    assert score_outcome("readout", "stopped", "futility").scored_as == "stopped"
    assert score_outcome("fda_decision", "CRL").scored_as == "CRL"


@pytest.mark.parametrize(
    ("status", "enrolled", "kind", "why", "reason", "cited"),
    [
        # NCT05951205 (Vertex, Phase 3, withdrawn, 0 enrolled)
        (
            "WITHDRAWN",
            0,
            "ACTUAL",
            "Modification to the clinical development plan",
            "withdrawn_before_enrollment",
            None,
        ),
        # NCT06598631 (Lilly, Phase 2, withdrawn, 0 enrolled): cites a related trial, no NCT number
        (
            "WITHDRAWN",
            0,
            "ACTUAL",
            "Study was terminated due to a lack of foreseeable clinical benefit in the proposed "
            "chronic kidney disease population, following the termination of a related heart "
            "failure study that demonstrated no benefit in an overlapping patient group.",
            "withdrawn_citing_other_trial",
            None,
        ),
        (
            "WITHDRAWN",
            0,
            "ACTUAL",
            "Withdrawn based on the results of NCT01234567.",
            "withdrawn_citing_other_trial",
            "NCT01234567",
        ),
        ("WITHDRAWN", None, None, "Sponsor decision", "withdrawn_before_enrollment", None),
        # Terminated with an actual enrollment of zero never enrolled anyone either.
        ("TERMINATED", 0, "ACTUAL", "Business reasons.", "withdrawn_before_enrollment", None),
    ],
)
def test_exclusions(status, enrolled, kind, why, reason, cited):
    ex = exclusion_for(status, enrolled, kind, why)
    assert ex is not None and (ex.reason, ex.cited_nct_id) == (reason, cited)


@pytest.mark.parametrize(
    ("status", "enrolled", "kind", "why"),
    [
        ("TERMINATED", 847, "ACTUAL", "Study terminated due to strategic business decision"),
        ("TERMINATED", 6, "ACTUAL", "Study terminated due to an inability to enroll participants."),
        ("TERMINATED", 0, "ESTIMATED", "Business reasons."),  # count never updated: still an event
        ("SUSPENDED", 120, "ACTUAL", "Clinical hold"),
    ],
)
def test_stops_after_enrollment_are_events(status, enrolled, kind, why):
    assert exclusion_for(status, enrolled, kind, why) is None

import pytest

from techbio.ledger.taxonomy import score_outcome


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

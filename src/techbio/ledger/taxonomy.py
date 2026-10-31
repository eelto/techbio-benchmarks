"""Outcome taxonomy v1 (operator-confirmed 2026-10-30). Mirrors docs/taxonomy.md exactly.

Void rule (operator override, narrow and public): an event is voided only if it is cancelled, or the
trial is stopped for reasons unrelated to its outcome (financing, strategic, acquisition). Anything
resolved by data is scored. Voided events are exported with their reason.
"""

from __future__ import annotations

from dataclasses import dataclass

TAXONOMY_VERSION = "v1"

EVENT_TYPES = ("readout", "fda_decision", "adcom", "discontinuation")

RESULTS: dict[str, tuple[str, ...]] = {
    "readout": ("met", "missed", "mixed", "stopped"),
    "fda_decision": ("approved", "CRL", "withdrawn"),
    "adcom": ("favorable", "unfavorable", "split"),
    "discontinuation": ("discontinued",),
}
ALL_RESULTS = tuple(dict.fromkeys(r for rs in RESULTS.values() for r in rs))

STOP_SUBTYPES = ("efficacy", "futility", "safety", "business", "operational")

EXPLANATIONS = (
    "efficacy",
    "safety",
    "regulatory_feedback",
    "manufacturing_cmc",
    "strategic_portfolio",
    "financial",
    "partner_decision",
    "enrollment_operational",
    "not_disclosed",
)

# Reserved fields: never tie-broken by a model; disagreement or low confidence goes to the human queue.
RESERVED_FIELDS = ("result_category", "sponsor_explanation_category")
RESERVED_CONFIDENCE_TAU = 0.8  # Q-C11 default

# Void reasons that are "unrelated to the outcome" (operator's examples: financing, strategic,
# acquisition). `operational` is my reading of "unrelated" and is flagged in docs/taxonomy.md.
VOID_STOP_SUBTYPES = {"business": "stopped_business", "operational": "stopped_operational"}
VOID_WITHDRAWAL_EXPLANATIONS = {"financial", "strategic_portfolio"}


@dataclass(frozen=True)
class Outcome:
    binary: int | None
    void_reason: str | None


def score_outcome(
    event_type: str,
    result: str,
    subtype: str | None = None,
    explanation: str | None = None,
    cancelled: bool = False,
    adcom_vote_held: bool = True,
) -> Outcome:
    """Binary outcome for scoring under taxonomy v1, or a void with its reason."""
    if cancelled:
        return Outcome(None, "cancelled")
    if event_type == "discontinuation":
        return Outcome(None, "not_scored_ledger_only")  # Q-A5: discontinuations are ledger-only
    if result not in RESULTS.get(event_type, ()):
        raise ValueError(f"result {result!r} is not valid for {event_type!r}")
    match event_type, result:
        case "readout", "met":
            return Outcome(1, None)
        case "readout", "missed" | "mixed":
            return Outcome(0, None)
        case "readout", "stopped":
            if subtype in VOID_STOP_SUBTYPES:
                return Outcome(None, VOID_STOP_SUBTYPES[subtype])
            if subtype == "efficacy":
                return Outcome(1, None)
            if subtype in ("futility", "safety"):
                return Outcome(0, None)
            raise ValueError("a stopped readout needs a subtype")
        case "fda_decision", "approved":
            return Outcome(1, None)
        case "fda_decision", "CRL":
            return Outcome(0, None)
        case "fda_decision", "withdrawn":
            if explanation in VOID_WITHDRAWAL_EXPLANATIONS:
                return Outcome(None, f"withdrawn_{explanation}")
            return Outcome(0, None)
        case "adcom", _ if not adcom_vote_held:
            return Outcome(None, "adcom_no_vote")
        case "adcom", "favorable":
            return Outcome(1, None)
        case "adcom", "unfavorable" | "split":
            # split = a tie on the deciding question (B5) = no majority in favor.
            return Outcome(0, None)
    raise AssertionError("unreachable")

"""Outcome taxonomy v1.1 (operator-confirmed 2026-10-30). Mirrors docs/taxonomy.md exactly.

Void rule (operator override, narrow and public): an event is voided only if it is cancelled, or the
trial is stopped for reasons unrelated to its outcome (financing, strategic, acquisition). Anything
resolved by data is scored. Voided events are exported with their reason.

v1.1 (operator, 2026-10-30, second round):
- A strategic/business stop after enrollment is void for endpoint scoring unless a data trigger is
  documented (interim analysis, futility, DSMB recommendation); then it is scored as "missed". Either
  way it is recorded as `strategic_stop_after_enrollment` with the enrolled-patient count.
- A trial withdrawn before enrolling anyone is not an event. One withdrawn citing another trial's
  data is not an event either, and is linked to that trial.
- A stop for failure to enroll is void, "operational" (confirmed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TAXONOMY_VERSION = "v1.1"

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

# Assigned by the ledger, never by an extractor: every business stop (all of them are after
# enrollment, because a trial withdrawn before enrollment is not an event).
STRATEGIC_STOP = "strategic_stop_after_enrollment"
DERIVED_EXPLANATIONS = (STRATEGIC_STOP,)

# Documented data triggers that make a business stop a scored "missed".
DATA_TRIGGERS = ("interim_analysis", "futility", "dsmb_recommendation")

# Reserved fields: never tie-broken by a model; a disagreement goes to the human queue. Agreement
# is accepted whatever the models' self-ratings (V.1, 2026-11-05) and checked by a random audit (V.2).
RESERVED_FIELDS = (
    "result_category",
    "result_subtype",
    "sponsor_explanation_category",
    "stop_data_trigger",
)

# Void reasons that are "unrelated to the outcome" (operator's examples: financing, strategic,
# acquisition). `operational` (failure to enroll) was confirmed by the operator on 2026-10-30.
VOID_STOP_SUBTYPES = {"business": "stopped_business", "operational": "stopped_operational"}
VOID_WITHDRAWAL_EXPLANATIONS = {"financial", "strategic_portfolio"}

EXCLUSION_REASONS = ("withdrawn_before_enrollment", "withdrawn_citing_other_trial")


@dataclass(frozen=True)
class Outcome:
    binary: int | None
    void_reason: str | None
    scored_as: str | None = None  # the result the binary scores (differs only for data triggers)


def score_outcome(
    event_type: str,
    result: str,
    subtype: str | None = None,
    explanation: str | None = None,
    cancelled: bool = False,
    adcom_vote_held: bool = True,
    data_trigger: str | None = None,
) -> Outcome:
    """Binary outcome for scoring under taxonomy v1.1, or a void with its reason."""
    o = _score(event_type, result, subtype, explanation, cancelled, adcom_vote_held, data_trigger)
    if o.binary is not None and o.scored_as is None:
        return Outcome(o.binary, None, result)
    return o


def _score(
    event_type: str,
    result: str,
    subtype: str | None,
    explanation: str | None,
    cancelled: bool,
    adcom_vote_held: bool,
    data_trigger: str | None,
) -> Outcome:
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
            if subtype == "business" and data_trigger in DATA_TRIGGERS:
                return Outcome(0, None, "missed")
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


def explanation_category(
    event_type: str, result: str | None, subtype: str | None, stated: str | None
) -> str | None:
    """The ledger's explanation category: the sponsor's stated one, except that every business stop
    is recorded as `strategic_stop_after_enrollment` so the pattern can be reported. The stated
    category is kept alongside it."""
    if event_type == "readout" and result == "stopped" and subtype == "business":
        return STRATEGIC_STOP
    return stated


@dataclass(frozen=True)
class Exclusion:
    reason: str
    cited_nct_id: str | None = None


NCT_RE = re.compile(r"\bNCT\d{8}\b", re.I)
_TRIAL = r"(?:study|studies|trial|trials|program)"
CITES_OTHER_TRIAL = re.compile(
    r"\b(?:another|other|related|sister|companion|parallel|separate)\s+(?:[\w-]+\s+){0,4}?"
    + _TRIAL
    # "termination of the study" is usually self-referential, so only results/data words count here.
    + r"|\b(?:results?|data|outcomes?|findings)\s+"
    r"(?:of|from|in)\s+(?:the\s+|a\s+|an\s+)?(?:[\w/-]+\s+){0,5}?" + _TRIAL + r"|" + NCT_RE.pattern,
    re.I,
)


def exclusion_for(
    status: str | None,
    enrolled: int | None,
    enrollment_type: str | None,
    why_stopped: str | None,
) -> Exclusion | None:
    """Registry records that are not events: withdrawn before enrollment (CT.gov WITHDRAWN, or
    TERMINATED/SUSPENDED with an actual enrollment of 0), and those withdrawn citing another
    trial's data. `cited_nct_id` is set when the record names the other trial's NCT number."""
    before = status == "WITHDRAWN" or (
        status in ("TERMINATED", "SUSPENDED") and enrolled == 0 and enrollment_type == "ACTUAL"
    )
    if not before:
        return None
    why = why_stopped or ""
    if CITES_OTHER_TRIAL.search(why):
        m = NCT_RE.search(why)
        return Exclusion("withdrawn_citing_other_trial", m.group(0).upper() if m else None)
    return Exclusion("withdrawn_before_enrollment")

"""Is a Phase 2 readout in scope? Taxonomy v1 (Q-B1): a Phase 2 trial counts as 2b only if it is
randomized and controlled, and the sponsor calls it 2b, pivotal or registrational or it enrolls 100
or more. The extractors apply the rule from the document; this checks their reading against the
registry before a statement reaches the ledger (pilot run 3: DENALI, two doses of one drug; both
tebapivat studies, one not randomized and one of 59 patients).

The registry settles phase, randomization and size. It can confirm a control (a placebo, sham or
no-treatment arm among the interventions, or a comparison in the title) but cannot rule one out:
sponsors often label an active-comparator arm "experimental" (2026-11-01: at least 10 of the 73
randomized Phase 2s with no comparator arm type had one). So a registry fact that fails the rule
drops the statement, an unconfirmed control goes to the operator, and where there is no registry
record a plain "Phase 2" goes to the operator and a "2b" keeps the extractors' reading.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, func, select

from techbio.core.db import trials
from techbio.ledger.sources.ctgov import TWO_B

CHECKED = (None, "2", "2b")  # readout phases the rule applies to; "2/3" and "3" are always in
_CONTROL_ARM = re.compile(
    r"placebo|vehicle|sham|saline|no intervention|observation|standard of care|best supportive",
    re.I,
)
_COMPARISON = re.compile(
    r"\bversus\b|\bvs\.?\s|compared (?:with|to)|investigator'?s choice|physician'?s choice|"
    r"standard of care|watchful waiting|placebo",
    re.I,
)
REGISTRY_FACTS = ("nct_id", "brief_title", "phases", "allocation", "enrollment", "interventions")


def registry_trial(
    conn: Connection, sponsor_id: str, nct_id: str | None, trial_name: str | None
) -> dict[str, Any] | None:
    """The registry record by NCT number, else by the sponsor's trial acronym if exactly one."""
    if nct_id:
        row = conn.execute(select(trials).where(trials.c.nct_id == nct_id)).mappings().first()
        if row:
            return dict(row)
    if trial_name:
        rows = (
            conn.execute(
                select(trials).where(
                    trials.c.sponsor_id == sponsor_id,
                    func.lower(trials.c.acronym) == trial_name.strip().lower(),
                )
            )
            .mappings()
            .all()
        )
        if len(rows) == 1:
            return dict(rows[0])
    return None


def controlled(t: dict[str, Any]) -> bool:
    """True when the registry shows a control; False means only "not shown"."""
    names = [i.get("name") or "" for i in t.get("interventions") or []]
    return any(_CONTROL_ARM.search(n) for n in names) or bool(
        _COMPARISON.search(t.get("brief_title") or "")
    )


def readout_scope(phase: str | None, t: dict[str, Any] | None) -> tuple[str, str]:
    """("in" | "out" | "ask", why) for a readout of a trial the extractors call `phase`."""
    if phase not in CHECKED:
        return "in", ""
    if t is None:
        if phase == "2":
            return "ask", "plain Phase 2 with no registry record: does it meet the 2b rule?"
        return "in", ""
    phases = set(t.get("phases") or [])
    if "PHASE3" in phases:
        return "in", ""
    if "PHASE2" not in phases or "PHASE1" in phases:
        return "out", f"registry: {'/'.join(sorted(phases)) or 'no phase'}, not Phase 2 or 3"
    alloc = t.get("allocation")
    if alloc is None:
        return "ask", "registry: randomization not stated"
    if alloc != "RANDOMIZED":
        return "out", f"registry: not randomized ({alloc})"
    n = t.get("enrollment") or 0
    if n < 100 and phase != "2b" and not TWO_B.search(t.get("brief_title") or ""):
        return "out", f"registry: {n} patients, not called 2b, pivotal or registrational"
    if not controlled(t):
        return "ask", "registry: randomized, but no control arm confirmed"
    return "in", ""


def facts(t: dict[str, Any] | None) -> dict[str, Any] | None:
    return {k: t.get(k) for k in REGISTRY_FACTS} if t else None

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

Before the 2b rule, every readout is checked for attribution (decision R.1): it is filed under the
trial's lead sponsor, so a partner's mention of another universe company's trial is dropped. The
2026-11-02 replay found one (Zai Lab on argenx's ALKIVIA). Another company's trial counts only if
it tests the statement's asset, so a wrong NCT number or a shared acronym (46 acronyms belong to
more than one sponsor) cannot drop a sponsor's own readout. With no registry record the extractors'
reading stands.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Connection, func, select

from techbio.core.db import trials
from techbio.ledger.names import assets_overlap
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
REGISTRY_FACTS = (
    "nct_id",
    "lead_sponsor_name",
    "brief_title",
    "phases",
    "allocation",
    "enrollment",
    "interventions",
)


def registry_trial(
    conn: Connection,
    sponsor_id: str,
    nct_id: str | None,
    trial_name: str | None,
    assets: list[str] | tuple[str, ...] = (),
) -> dict[str, Any] | None:
    """The registry record by NCT number, else by the sponsor's trial acronym if exactly one, else
    by the acronym of the one other company's trial that tests one of `assets`."""
    if nct_id:
        row = conn.execute(select(trials).where(trials.c.nct_id == nct_id)).mappings().first()
        if row:
            return dict(row)
    if trial_name:
        rows = (
            conn.execute(
                select(trials).where(func.lower(trials.c.acronym) == trial_name.strip().lower())
            )
            .mappings()
            .all()
        )
        own = [r for r in rows if r["sponsor_id"] == sponsor_id]
        if own:
            return dict(own[0]) if len(own) == 1 else None
        others = [r for r in rows if tests_asset(r, assets)]
        if len(others) == 1:
            return dict(others[0])
    return None


def tests_asset(t: dict[str, Any], assets: list[str] | tuple[str, ...]) -> bool:
    """The trial's interventions or title name one of the asset's names. Titles count because
    interventions are often abbreviated (ALKIVIA lists efgartigimod as "EFG PH20 SC")."""
    names = [i.get("name") or "" for i in t.get("interventions") or []]
    return bool(assets) and assets_overlap(list(assets), [*names, t.get("brief_title") or ""])


def attribution(
    sponsor_id: str, assets: list[str] | tuple[str, ...], t: dict[str, Any] | None
) -> tuple[str, str]:
    """("in" | "out", why) under R.1: "out" when another company in the universe leads the trial."""
    if t is None or t.get("sponsor_id") in (None, sponsor_id) or not tests_asset(t, assets):
        return "in", ""
    return "out", (
        f"registry: {t['nct_id']} is led by {t.get('lead_sponsor_name')}, another company in the "
        "universe; a readout is filed under its lead sponsor (R.1)"
    )


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

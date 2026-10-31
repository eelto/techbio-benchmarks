"""Registry records that are not events (taxonomy v1.1, operator decision 2026-10-30).

A trial withdrawn before enrolling anyone never had a readout, so it is not an event; one withdrawn
citing another trial's data is not an event either, and is linked to the trial it cites. Exclusions
are recorded (and exported with their reasons and links) rather than silently skipped, and an open
event that turns out to belong to an excluded trial is closed as `excluded`.

When a record cites another trial without its NCT number, the operator picks the trial in
`ledger review` (reason `exclusion_link`); candidates are the sponsor's other registry records,
computed when the item is shown so that trials ingested later are included.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Connection, select, update

from techbio.core.db import events, exclusions, now, review_queue, trials
from techbio.core.ids import new_id
from techbio.ledger.apply import Provenance, add_label
from techbio.ledger.names import assets_overlap
from techbio.ledger.taxonomy import TAXONOMY_VERSION, Exclusion

PARSER = "parser:ctgov_why_stopped_v1"


def record_exclusion(
    conn: Connection, *, source_id: str, sponsor_id: str, trial: dict[str, Any], ex: Exclusion
) -> bool:
    """Record one exclusion (idempotent per trial). Returns True if it is new."""
    nct = trial["nct_id"]
    if conn.execute(select(exclusions.c.nct_id).where(exclusions.c.nct_id == nct)).first():
        return False
    t = now()
    conn.execute(
        exclusions.insert().values(
            exclusion_id=new_id("exc"),
            nct_id=nct,
            sponsor_id=sponsor_id,
            source_id=source_id,
            reason=ex.reason,
            enrolled=trial.get("enrollment"),
            linked_nct_id=ex.cited_nct_id,
            linked_by=PARSER if ex.cited_nct_id else None,
            linked_recorded_at=t if ex.cited_nct_id else None,
            taxonomy_version=TAXONOMY_VERSION,
            recorded_at=t,
        )
    )
    if ex.reason == "withdrawn_citing_other_trial" and not ex.cited_nct_id:
        conn.execute(
            review_queue.insert().values(
                item_id=new_id("rq"),
                source_id=source_id,
                field="linked_nct_id",
                reason="exclusion_link",
                payload={
                    "source_id": source_id,
                    "sponsor_id": sponsor_id,
                    "nct_id": nct,
                    "url": f"https://clinicaltrials.gov/study/{nct}",
                    "statement_date": (trial.get("last_update_posted") or date.today()).isoformat(),
                    "why_stopped": trial.get("why_stopped"),
                    "interventions": [i["name"] for i in trial.get("interventions") or []],
                    "statement": {"asset_name": None, "kind": "exclusion", "nct_id": nct},
                },
                status="open",
                created_at=t,
            )
        )
    _close_open_events(conn, nct, ex, source_id, sponsor_id)
    return True


def _close_open_events(
    conn: Connection, nct: str, ex: Exclusion, source_id: str, sponsor_id: str
) -> None:
    prov = Provenance(source_id, sponsor_id, datetime.now(UTC).date(), PARSER, "deterministic")
    for row in conn.execute(
        select(events.c.event_id).where(events.c.nct_id == nct, events.c.status == "open")
    ).all():
        add_label(conn, row.event_id, "excluded", ex.reason, prov)
        conn.execute(
            update(events)
            .where(events.c.event_id == row.event_id)
            .values(status="excluded", updated_recorded_at=now())
        )


def link_candidates(conn: Connection, sponsor_id: str, nct_id: str) -> list[dict[str, Any]]:
    """The sponsor's other registry records, those sharing an intervention name first."""
    me = conn.execute(select(trials.c.interventions).where(trials.c.nct_id == nct_id)).first()
    mine = [i["name"] for i in (me.interventions if me else None) or []]
    rows = (
        conn.execute(
            select(
                trials.c.nct_id,
                trials.c.brief_title,
                trials.c.overall_status,
                trials.c.interventions,
                trials.c.phases,
            ).where(trials.c.sponsor_id == sponsor_id, trials.c.nct_id != nct_id)
        )
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        names = [i["name"] for i in r["interventions"] or []]
        out.append(
            {
                "nct_id": r["nct_id"],
                "title": r["brief_title"],
                "status": r["overall_status"],
                "phases": r["phases"],
                "shared_intervention": bool(mine and names and assets_overlap(mine, names)),
            }
        )
    stopped = {"TERMINATED", "SUSPENDED", "WITHDRAWN", "COMPLETED"}
    out.sort(key=lambda c: (not c["shared_intervention"], c["status"] not in stopped, c["nct_id"]))
    return out


def set_link(conn: Connection, nct_id: str, linked_nct_id: str | None, by: str) -> None:
    """Operator decision on an `exclusion_link` item. No link means the record did not in fact cite
    another trial, so it is reclassified as withdrawn before enrollment."""
    values: dict[str, Any] = {
        "linked_nct_id": linked_nct_id,
        "linked_by": by,
        "linked_recorded_at": now(),
    }
    if linked_nct_id is None:
        values["reason"] = "withdrawn_before_enrollment"
    conn.execute(update(exclusions).where(exclusions.c.nct_id == nct_id).values(**values))

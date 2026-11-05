"""Apply parsed Federal Register AdCom notices to the ledger (no model calls)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Engine, select, update

from techbio.core.db import sources, sponsors
from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.names import same_company

PARSER = "parser:fedreg_adcom_v1"


def apply_notices(engine: Engine) -> dict[str, int]:
    stats = {
        "notices": 0,
        "applications": 0,
        "in_universe": 0,
        "events_created": 0,
        "cancelled": 0,
        "ambiguous": 0,
    }
    with engine.connect() as conn:
        spons = conn.execute(select(sponsors.c.sponsor_id, sponsors.c.name)).all()
        notices = (
            conn.execute(
                select(sources)
                .where(sources.c.type == "fedreg_adcom", sources.c.extract_status == "none")
                .order_by(sources.c.published_at)
            )
            .mappings()
            .all()
        )
    for src in notices:
        stats["notices"] += 1
        meta = src["meta"]
        meeting = date.fromisoformat(meta["meeting_date"]) if meta.get("meeting_date") else None
        with engine.begin() as conn:
            for app in meta.get("applications", []):
                stats["applications"] += 1
                sp = next(
                    (
                        s
                        for s in spons
                        if app.get("sponsor") and same_company(app["sponsor"], s.name)
                    ),
                    None,
                )
                if sp is None or not app.get("drug"):
                    continue  # private sponsors and unparsed agendas stay out of the ledger
                stats["in_universe"] += 1
                st = Statement(
                    kind="cancellation" if meta.get("cancelled") else "guidance",
                    event_type="adcom",
                    asset_name=app["drug"],
                    indication=app.get("indication"),
                    application_no=app["number"],
                    application_kind=app["kind"],
                    timing_text=meeting.isoformat() if meeting else None,
                    window_start=meeting,
                    window_end=meeting,
                    window_precision="day" if meeting else None,
                    event_date=meeting if meta.get("cancelled") else None,
                )
                prov = Provenance(
                    src["source_id"],
                    sp.sponsor_id,
                    src["published_at"].date(),
                    PARSER,
                    "deterministic",
                )
                res = apply_statement(conn, st, prov)
                stats["events_created"] += int(res.created_event)
                stats["cancelled"] += int(meta.get("cancelled", False))
                stats["ambiguous"] += int(bool(res.ambiguous))
            conn.execute(
                update(sources)
                .where(sources.c.source_id == src["source_id"])
                .values(extract_status="done")
            )
    return stats

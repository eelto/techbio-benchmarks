"""Ledger summary (printed after every refresh) and the sample export for milestone write-ups.

Exports carry structured facts and links only: never press-release text, quotes or passages.
"""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select

from techbio.core.db import events, promises, resolutions, sources, spend_ledger, sponsors
from techbio.ledger.review import queue_size
from techbio.ledger.slip import event_slips, slip_summary


def _latest_promises(conn) -> dict[str, Any]:
    rows = (
        conn.execute(
            select(promises).order_by(
                promises.c.event_id, promises.c.statement_date, promises.c.recorded_at
            )
        )
        .mappings()
        .all()
    )
    latest: dict[str, Any] = {}
    for r in rows:
        latest[r["event_id"]] = r
    return latest


def scope_events(
    engine: Engine, today: date | None = None, days: int = 90
) -> dict[str, list[dict[str, Any]]]:
    """Upcoming: open events whose current guided window overlaps [today, today+days].
    Resolved: resolutions (incl. voids) with event_date in [today-days, today]."""
    today = today or datetime.now(UTC).date()
    with engine.connect() as conn:
        latest = _latest_promises(conn)
        evs = {
            r["event_id"]: dict(r)
            for r in conn.execute(
                select(events, sponsors.c.name.label("sponsor"), sponsors.c.tickers).join(sponsors)
            ).mappings()
        }
        res = {r["event_id"]: dict(r) for r in conn.execute(select(resolutions)).mappings()}
        urls = dict(conn.execute(select(sources.c.source_id, sources.c.url)).all())
    upcoming, resolved = [], []
    for eid, e in evs.items():
        p = latest.get(eid)
        if (
            e["status"] == "open"
            and p
            and p["guided_start"] <= today + timedelta(days=days)
            and p["guided_end"] >= today
        ):
            upcoming.append(
                {
                    **e,
                    "guided_text": p["guided_text"],
                    "guided_start": p["guided_start"],
                    "guided_end": p["guided_end"],
                    "source_url": urls.get(p["source_id"]),
                }
            )
        r = res.get(eid)
        if r and today - timedelta(days=days) <= r["event_date"] <= today:
            resolved.append(
                {
                    **e,
                    **{
                        k: r[k]
                        for k in (
                            "event_date",
                            "result_category",
                            "result_subtype",
                            "sponsor_explanation_category",
                            "outcome_binary",
                            "void_reason",
                            "taxonomy_version",
                            "confirmed_by",
                        )
                    },
                    "source_url": urls.get(r["primary_source_id"]),
                }
            )
    upcoming.sort(key=lambda x: (x["guided_end"], x["guided_start"]))
    resolved.sort(key=lambda x: x["event_date"], reverse=True)
    return {"upcoming": upcoming, "resolved": resolved}


def summary(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conn:
        n_spon = conn.execute(
            select(func.count()).select_from(sponsors).where(sponsors.c.in_universe_to.is_(None))
        ).scalar_one()
        by_src = dict(
            conn.execute(select(sources.c.type, func.count()).group_by(sources.c.type)).all()
        )
        pf = dict(
            conn.execute(
                select(sources.c.prefilter_status, func.count()).group_by(
                    sources.c.prefilter_status
                )
            ).all()
        )
        ev = conn.execute(
            select(events.c.event_type, events.c.date_type, events.c.status, func.count()).group_by(
                events.c.event_type, events.c.date_type, events.c.status
            )
        ).all()
        voids = conn.execute(
            select(resolutions.c.void_reason, func.count())
            .where(resolutions.c.void_reason.is_not(None))
            .group_by(resolutions.c.void_reason)
        ).all()
        unconfirmed = conn.execute(
            select(func.count())
            .select_from(resolutions)
            .where(resolutions.c.confirmed_by.is_(None), resolutions.c.outcome_binary.is_not(None))
        ).scalar_one()
        month0 = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spend_month = conn.execute(
            select(func.coalesce(func.sum(spend_ledger.c.actual_usd), 0.0)).where(
                spend_ledger.c.started_at >= month0
            )
        ).scalar_one()
        slips = slip_summary(conn)
    scope = scope_events(engine)
    return {
        "sponsors_in_universe": n_spon,
        "sources_by_type": by_src,
        "prefilter": pf,
        "events": [{"event_type": t, "date_type": d, "status": s, "n": n} for t, d, s, n in ev],
        "upcoming_90d": len(scope["upcoming"]),
        "upcoming_90d_by_date_type": {
            k: sum(1 for e in scope["upcoming"] if e["date_type"] == k) for k in ("dated", "fuzzy")
        },
        "resolved_last_90d": len(scope["resolved"]),
        "voids": dict(voids),
        "resolutions_awaiting_operator_confirmation": unconfirmed,
        "queue": queue_size(engine),
        "slips": slips,
        "spend_this_month_usd": round(float(spend_month), 2),
    }


SAMPLE_COLUMNS = (
    "event_id",
    "sponsor",
    "tickers",
    "event_type",
    "date_type",
    "asset_name",
    "indication",
    "phase",
    "trial_name",
    "nct_id",
    "status",
    "guided_text",
    "guided_start",
    "guided_end",
    "restatements",
    "slips",
    "event_date",
    "result_category",
    "result_subtype",
    "sponsor_explanation_category",
    "outcome_binary",
    "void_reason",
    "source_url",
)


def write_sample(engine: Engine, path: Path, n: int = 25) -> int:
    """Structured rows + links only (S7: never raw text)."""
    scope = scope_events(engine)
    with engine.connect() as conn:
        slips = event_slips(conn)
    rows = scope["upcoming"][:n] + scope["resolved"][:n]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            s = slips.get(r["event_id"], {})
            w.writerow(
                {
                    **r,
                    "tickers": " ".join(r["tickers"]),
                    "restatements": s.get("restatements"),
                    "slips": s.get("slips"),
                }
            )
    return len(rows)

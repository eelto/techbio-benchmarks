"""Slip tracking: how guided timing moves between restatements, and guided vs actual."""

from __future__ import annotations

import itertools
from collections import defaultdict
from statistics import median
from typing import Any

from sqlalchemy import Connection, select

from techbio.core.db import events, promises, resolutions


def event_slips(conn: Connection) -> dict[str, dict[str, Any]]:
    """Per event: number of restatements, number of slips (guided end moved later), total slip days,
    first/current guided window, and realized slip (actual date - first guided end) if resolved."""
    rows = conn.execute(
        select(
            promises.c.event_id,
            promises.c.statement_date,
            promises.c.guided_start,
            promises.c.guided_end,
            promises.c.guided_text,
        ).order_by(promises.c.event_id, promises.c.statement_date, promises.c.recorded_at)
    ).all()
    actual = dict(conn.execute(select(resolutions.c.event_id, resolutions.c.event_date)).all())
    by_event: dict[str, list] = defaultdict(list)
    for r in rows:
        by_event[r.event_id].append(r)
    out: dict[str, dict[str, Any]] = {}
    for eid, ps in by_event.items():
        slips = [
            (b.guided_end - a.guided_end).days
            for a, b in itertools.pairwise(ps)
            if b.guided_end > a.guided_end
        ]
        first, cur = ps[0], ps[-1]
        out[eid] = {
            "restatements": len(ps),
            "slips": len(slips),
            "slip_days": sum(slips),
            "first_guided": [first.guided_start.isoformat(), first.guided_end.isoformat()],
            "current_guided": [cur.guided_start.isoformat(), cur.guided_end.isoformat()],
            "current_text": cur.guided_text,
            "realized_slip_days": (actual[eid] - first.guided_end).days if eid in actual else None,
        }
    return out


def slip_summary(conn: Connection) -> dict[str, Any]:
    per = event_slips(conn)
    types = dict(conn.execute(select(events.c.event_id, events.c.event_type)).all())
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for eid, s in per.items():
        by_type[types.get(eid, "?")].append(s)
    summary: dict[str, Any] = {}
    for t, items in by_type.items():
        realized = [s["realized_slip_days"] for s in items if s["realized_slip_days"] is not None]
        summary[t] = {
            "events_with_guidance": len(items),
            "events_slipped": sum(1 for s in items if s["slips"]),
            "median_realized_slip_days": median(realized) if realized else None,
            "n_realized": len(realized),
        }
    return summary

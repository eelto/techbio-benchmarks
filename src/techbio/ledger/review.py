"""`ledger review`: the human queue, one item at a time.

Each item shows the event, both model answers (and the tie-break's, if any), confidences, and the
exact supporting passages from the local copy of the source, with its link. The operator picks A or
B, types a value, links to an existing event, or skips. The decision is written as a new label
version (`human:<reviewer>`) through the same apply path as automatic decisions.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import Engine, func, select, update

from techbio.core.db import now, review_queue, sources
from techbio.ledger import prefilter
from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.taxonomy import ALL_RESULTS, EXPLANATIONS, STOP_SUBTYPES

ALLOWED = {
    "result_category": ALL_RESULTS,
    "result_subtype": STOP_SUBTYPES,
    "sponsor_explanation_category": EXPLANATIONS,
}


def queue_size(engine: Engine) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(review_queue.c.reason, func.count())
            .where(review_queue.c.status == "open")
            .group_by(review_queue.c.reason)
        ).all()
    d = {r[0]: r[1] for r in rows}
    d["total"] = sum(d.values())
    return d


def _passage(src_path: str, content_type: str | None, quote: str | None, width: int = 400) -> str:
    if not quote:
        return "(no quote)"
    text = prefilter.load_text(src_path, content_type)
    norm = " ".join(text.split())
    q = " ".join(quote.split())
    i = norm.find(q[:60])
    if i < 0:
        return f"(quote not found verbatim) {quote}"
    start = max(0, i - width // 2)
    return (
        "…"
        + norm[start:i]
        + "[bold yellow]"
        + norm[i : i + len(q)]
        + "[/]"
        + norm[i + len(q) : i + len(q) + width // 2]
        + "…"
    )


def render(console: Console, item: dict[str, Any], src: dict[str, Any]) -> None:
    p = item["payload"]
    console.rule(f"[bold]{item['reason']}[/] · field: {item['field']} · {item['item_id']}")
    st = p.get("statement", {})
    console.print(
        f"[bold]{st.get('event_type')}[/] · {st.get('asset_name')} · {st.get('indication') or ''} · "
        f"trial {st.get('trial_name') or st.get('nct_id') or '?'} · kind {st.get('kind')}"
    )
    console.print(f"source: {p.get('url')} (published {p.get('statement_date')})")
    cands = p.get("candidates")
    if isinstance(cands, dict):
        t = Table(show_lines=True)
        t.add_column("field")
        for k in ("A", "B"):
            t.add_column(
                f"{k} ({(p.get('models') or {}).get(k)}) conf {(p.get('confidence') or {}).get(k)}"
            )
        fields = [f for f in item["field"].split(",") if f and f != "exists"] or [
            "result_category",
            "result_subtype",
            "sponsor_explanation_category",
            "window_start",
            "window_end",
            "event_date",
        ]
        for f in fields:
            t.add_row(f, *[str((p["candidates"].get(k) or {}).get(f)) for k in ("A", "B")])
        console.print(t)
        for k in ("A", "B"):
            q = (p.get("quotes") or {}).get(k)
            if q:
                console.print(
                    Panel(_passage(src["local_path"], src["content_type"], q), title=f"passage {k}")
                )
    if p.get("tiebreak"):
        console.print(f"tie-break: {json.dumps(p['tiebreak'])[:600]}")
    if item["reason"] == "event_link_ambiguous":
        t = Table(title="candidate events")
        for col in ("#", "event_id", "asset", "indication", "trial", "status"):
            t.add_column(col)
        for i, c in enumerate(p["candidates"], 1):
            t.add_row(
                str(i),
                c["event_id"],
                c["asset_name"],
                c.get("indication") or "",
                c.get("trial_name") or c.get("nct_id") or "",
                c["status"],
            )
        console.print(t)


def decide(
    engine: Engine,
    item: dict[str, Any],
    choice: str,
    reviewer: str,
    value: Any = None,
    event_id: str | None = None,
    note: str | None = None,
) -> str | None:
    """Apply an operator decision. choice: A | B | value | link | new | reject | skip."""
    p = item["payload"]
    with engine.begin() as conn:
        if choice == "skip":
            conn.execute(
                update(review_queue)
                .where(review_queue.c.item_id == item["item_id"])
                .values(status="skipped")
            )
            return None
        if choice == "reject":
            conn.execute(
                update(review_queue)
                .where(review_queue.c.item_id == item["item_id"])
                .values(status="closed", closed_at=now(), closed_by=f"human:{reviewer}")
            )
            return None
        st = Statement.from_json(p["statement"])
        if choice in ("A", "B"):
            chosen = p["candidates"][choice]
            if chosen is None:
                raise ValueError(f"candidate {choice} is empty")
            st = Statement.from_json(chosen)
        elif choice == "value":
            for f, v in (value or {}).items():
                if f in ALLOWED and v is not None and v not in ALLOWED[f]:
                    raise ValueError(f"{v!r} is not a valid {f}")
                setattr(
                    st,
                    f,
                    date.fromisoformat(v)
                    if f in ("event_date", "window_start", "window_end") and v
                    else v,
                )
        prov = Provenance(
            p["source_id"],
            p["sponsor_id"],
            date.fromisoformat(p["statement_date"]),
            f"human:{reviewer}",
            "human",
            note,
        )
        target = event_id if choice == "link" else None
        if choice == "new":
            from techbio.ledger.apply import create_event

            target = create_event(conn, p["sponsor_id"], st)
        res = apply_statement(conn, st, prov, event_id=target)
        if res.ambiguous:
            raise ValueError(
                "still ambiguous: link to one of the candidate events or create a new one"
            )
        conn.execute(
            update(review_queue)
            .where(review_queue.c.item_id == item["item_id"])
            .values(
                status="closed",
                closed_at=now(),
                closed_by=f"human:{reviewer}",
                event_id=res.event_id,
            )
        )
        return res.event_id


def open_items(engine: Engine, limit: int | None = None) -> list[dict[str, Any]]:
    q = (
        select(review_queue)
        .where(review_queue.c.status == "open")
        .order_by(review_queue.c.created_at)
    )
    if limit:
        q = q.limit(limit)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings().all()]


def interactive(
    engine: Engine, reviewer: str, ask: Callable[[str], str] = input, console: Console | None = None
) -> dict[str, int]:
    console = console or Console()
    stats = {"decided": 0, "skipped": 0}
    console.print(f"queue: {queue_size(engine)}")
    for item in open_items(engine):
        with engine.connect() as conn:
            src = dict(
                conn.execute(select(sources).where(sources.c.source_id == item["source_id"]))
                .mappings()
                .one()
            )
        render(console, item, src)
        while True:
            if item["reason"] == "event_link_ambiguous":
                ans = (
                    ask("[#] link to candidate · [n]ew event · [r]eject · [s]kip · [q]uit > ")
                    .strip()
                    .lower()
                )
            else:
                ans = (
                    ask(
                        "[a]/[b] pick · [v]alue · [r]eject (not an in-scope fact) · [s]kip · [q]uit > "
                    )
                    .strip()
                    .lower()
                )
            try:
                if ans == "q":
                    return stats
                if ans == "s":
                    decide(engine, item, "skip", reviewer)
                    stats["skipped"] += 1
                elif ans in ("a", "b"):
                    decide(
                        engine,
                        item,
                        ans.upper(),
                        reviewer,
                        note=ask("note (enter to skip) > ") or None,
                    )
                    stats["decided"] += 1
                elif ans == "v":
                    raw = ask('JSON of field values, e.g. {"result_category": "missed"} > ')
                    decide(
                        engine,
                        item,
                        "value",
                        reviewer,
                        value=json.loads(raw),
                        note=ask("note > ") or None,
                    )
                    stats["decided"] += 1
                elif ans == "r":
                    decide(engine, item, "reject", reviewer)
                    stats["decided"] += 1
                elif ans == "n":
                    decide(engine, item, "new", reviewer)
                    stats["decided"] += 1
                elif ans.isdigit() and item["reason"] == "event_link_ambiguous":
                    cand = item["payload"]["candidates"][int(ans) - 1]
                    decide(engine, item, "link", reviewer, event_id=cand["event_id"])
                    stats["decided"] += 1
                else:
                    continue
                break
            except (ValueError, IndexError, json.JSONDecodeError) as e:
                console.print(f"[red]{e}[/]")
    return stats

"""Write accepted statements into the ledger: events, promises (slip input), labels, resolutions.

The auto-accept path, the tie-break path and `ledger review` all call `apply_statement`, so a fact
lands the same way whoever decided it. Labels are append-only: a new value is a new version that
supersedes the old one, with its reviewer and recording time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Connection, func, select, update

from techbio.core.db import events, label_sources, labels, now, promises, resolutions, sources
from techbio.core.ids import new_id
from techbio.ledger.names import asset_key, assets_overlap
from techbio.ledger.taxonomy import TAXONOMY_VERSION, score_outcome


@dataclass
class Statement:
    kind: str  # guidance | outcome | discontinuation | cancellation
    event_type: str
    asset_name: str
    asset_aliases: list[str] = field(default_factory=list)
    indication: str | None = None
    nct_id: str | None = None
    trial_name: str | None = None
    phase: str | None = None
    application_kind: str | None = None
    application_no: str | None = None
    timing_text: str | None = None
    window_start: date | None = None
    window_end: date | None = None
    window_precision: str | None = None
    event_date: date | None = None
    result_category: str | None = None
    result_subtype: str | None = None
    sponsor_explanation_category: str | None = None
    quote: str | None = None
    adcom_vote_held: bool = True

    def names(self) -> list[str]:
        return [self.asset_name, *self.asset_aliases]

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("window_start", "window_end", "event_date"):
            d[k] = d[k].isoformat() if d[k] else None
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Statement:
        d = dict(d)
        for k in ("window_start", "window_end", "event_date"):
            d[k] = date.fromisoformat(d[k]) if d.get(k) else None
        return cls(**d)


@dataclass
class Provenance:
    source_id: str
    sponsor_id: str
    statement_date: date
    reviewer: str
    reviewer_kind: str  # human | model-adjudicated | auto-agreement | deterministic
    note: str | None = None


@dataclass
class ApplyResult:
    event_id: str | None
    created_event: bool = False
    ambiguous: list[dict[str, Any]] = field(default_factory=list)
    resolved: bool = False


def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().replace("-", " ").split())


def candidate_events(conn: Connection, sponsor_id: str, st: Statement) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            select(events).where(
                events.c.sponsor_id == sponsor_id, events.c.event_type == st.event_type
            )
        )
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        if st.application_no and r["application_no"] and st.application_no == r["application_no"]:
            out.append(dict(r))
            continue
        if not assets_overlap(st.names(), [r["asset_name"], *r["asset_aliases"]]):
            continue
        if st.nct_id and r["nct_id"] and st.nct_id != r["nct_id"]:
            continue
        if st.trial_name and r["trial_name"] and _norm(st.trial_name) != _norm(r["trial_name"]):
            continue
        out.append(dict(r))
    if len(out) > 1:
        # Prefer exact trial identity, then open events, then indication word overlap.
        exact = [
            r
            for r in out
            if (st.nct_id and r["nct_id"] == st.nct_id)
            or (st.trial_name and _norm(r["trial_name"]) == _norm(st.trial_name))
        ]
        if exact:
            out = exact
    if len(out) > 1 and st.kind == "guidance":
        open_ = [r for r in out if r["status"] == "open"]
        out = open_ or out
    if len(out) > 1 and st.indication:
        words = set(_norm(st.indication).split()) - {
            "of",
            "the",
            "and",
            "with",
            "in",
            "for",
            "patients",
            "adults",
            "adult",
        }
        scored = sorted(out, key=lambda r: -len(words & set(_norm(r["indication"]).split())))
        top = len(words & set(_norm(scored[0]["indication"]).split()))
        out = (
            [r for r in scored if len(words & set(_norm(r["indication"]).split())) == top]
            if top
            else out
        )
    return out


def _dedup_key(sponsor_id: str, st: Statement) -> str:
    ident = (
        st.application_no or st.nct_id or _norm(st.trial_name) or _norm(st.indication)[:60] or "-"
    )
    return f"{st.event_type}|{sponsor_id}|{asset_key(st.asset_name)}|{ident}"


def create_event(conn: Connection, sponsor_id: str, st: Statement) -> str:
    key = _dedup_key(sponsor_id, st)
    existing = conn.execute(select(events.c.event_id).where(events.c.dedup_key == key)).first()
    if existing:
        return existing.event_id
    eid = new_id("evt")
    t = now()
    date_type = "dated" if st.window_precision == "day" else "fuzzy"
    conn.execute(
        events.insert().values(
            event_id=eid,
            event_type=st.event_type,
            date_type=date_type,
            sponsor_id=sponsor_id,
            asset_name=st.asset_name,
            asset_aliases=sorted(set(st.asset_aliases) - {st.asset_name}),
            indication=st.indication,
            nct_id=st.nct_id,
            trial_name=st.trial_name,
            phase=st.phase,
            application_no=st.application_no,
            application_kind=st.application_kind,
            status="open",
            dedup_key=key,
            created_recorded_at=t,
            updated_recorded_at=t,
        )
    )
    return eid


def _enrich_event(conn: Connection, event_id: str, st: Statement) -> None:
    """Fill identity gaps (aliases, NCT, trial name) learned from later documents."""
    r = conn.execute(select(events).where(events.c.event_id == event_id)).mappings().one()
    changes: dict[str, Any] = {}
    aliases = set(r["asset_aliases"]) | set(st.names())
    aliases.discard(r["asset_name"])
    if aliases != set(r["asset_aliases"]):
        changes["asset_aliases"] = sorted(aliases)
    for col in (
        "nct_id",
        "trial_name",
        "phase",
        "application_no",
        "application_kind",
        "indication",
    ):
        if not r[col] and getattr(st, col):
            changes[col] = getattr(st, col)
    if changes:
        changes["updated_recorded_at"] = now()
        conn.execute(update(events).where(events.c.event_id == event_id).values(**changes))


def add_label(
    conn: Connection,
    event_id: str,
    field_name: str,
    value: Any,
    prov: Provenance,
    valid_at: datetime | None = None,
    passage: dict[str, Any] | None = None,
) -> str | None:
    """Append a label version. Returns None if the current value is already this value."""
    cur = conn.execute(
        select(labels.c.label_id, labels.c.value, labels.c.version)
        .where(labels.c.event_id == event_id, labels.c.field == field_name)
        .order_by(labels.c.version.desc())
        .limit(1)
    ).first()
    if cur and cur.value == value:
        # Same fact from another document: record the extra source, keep the label.
        linked = conn.execute(
            select(label_sources.c.label_id).where(
                label_sources.c.label_id == cur.label_id,
                label_sources.c.source_id == prov.source_id,
            )
        ).first()
        if not linked:
            conn.execute(
                label_sources.insert().values(
                    label_id=cur.label_id, source_id=prov.source_id, passage_ref=passage
                )
            )
        return None
    lid = new_id("lbl")
    conn.execute(
        labels.insert().values(
            label_id=lid,
            event_id=event_id,
            field=field_name,
            value=value,
            reviewer=prov.reviewer,
            reviewer_kind=prov.reviewer_kind,
            version=(cur.version + 1) if cur else 1,
            valid_at=valid_at,
            recorded_at=now(),
            supersedes_label_id=cur.label_id if cur else None,
            note=prov.note,
        )
    )
    conn.execute(
        label_sources.insert().values(label_id=lid, source_id=prov.source_id, passage_ref=passage)
    )
    return lid


def current_labels(conn: Connection, event_id: str) -> dict[str, Any]:
    sub = (
        select(labels.c.field, func.max(labels.c.version).label("v"))
        .where(labels.c.event_id == event_id)
        .group_by(labels.c.field)
        .subquery()
    )
    rows = conn.execute(
        select(labels.c.field, labels.c.value, labels.c.label_id)
        .join(sub, (labels.c.field == sub.c.field) & (labels.c.version == sub.c.v))
        .where(labels.c.event_id == event_id)
    ).all()
    return {r.field: (r.value, r.label_id) for r in rows}


def add_promise(conn: Connection, event_id: str, st: Statement, prov: Provenance) -> bool:
    if not (st.window_start and st.window_end and st.timing_text):
        return False
    exists = conn.execute(
        select(promises.c.promise_id).where(
            promises.c.event_id == event_id, promises.c.source_id == prov.source_id
        )
    ).first()
    if exists:
        return False
    conn.execute(
        promises.insert().values(
            promise_id=new_id("prm"),
            event_id=event_id,
            statement_date=prov.statement_date,
            guided_text=st.timing_text,
            guided_start=st.window_start,
            guided_end=st.window_end,
            guided_precision=st.window_precision or "range",
            source_id=prov.source_id,
            reviewer_kind=prov.reviewer_kind,
            recorded_at=now(),
        )
    )
    latest = conn.execute(
        select(promises.c.guided_precision)
        .where(promises.c.event_id == event_id)
        .order_by(promises.c.statement_date.desc(), promises.c.recorded_at.desc())
        .limit(1)
    ).first()
    conn.execute(
        update(events)
        .where(events.c.event_id == event_id)
        .values(
            date_type="dated" if latest.guided_precision == "day" else "fuzzy",
            updated_recorded_at=now(),
        )
    )
    return True


def resolve_event(
    conn: Connection, event_id: str, prov: Provenance, cancelled: bool = False
) -> bool:
    """Derive the resolution from current labels under the current taxonomy version."""
    ev = conn.execute(select(events).where(events.c.event_id == event_id)).mappings().one()
    cur = current_labels(conn, event_id)
    result = cur.get("result_category", (None, None))
    if result[0] is None and not cancelled:
        return False
    is_primary = conn.execute(
        select(sources.c.is_primary).where(sources.c.source_id == prov.source_id)
    ).scalar_one()
    if not is_primary:
        raise ValueError("resolutions need a primary source (S9)")
    subtype = cur.get("result_subtype", (None, None))[0]
    expl = cur.get("sponsor_explanation_category", (None, None))[0]
    vote_held = cur.get("adcom_vote_held", (True, None))[0]
    if cancelled:
        outcome = score_outcome(ev["event_type"], "", cancelled=True)
    else:
        outcome = score_outcome(
            ev["event_type"], result[0], subtype, expl, adcom_vote_held=bool(vote_held)
        )
    ed = cur.get("event_date", (None, None))[0]
    event_date = date.fromisoformat(ed) if ed else prov.statement_date
    label_id = result[1] or cur.get("cancelled", (None, None))[1]
    values = dict(
        label_id=label_id,
        primary_source_id=prov.source_id,
        event_date=event_date,
        result_category=result[0],
        result_subtype=subtype,
        sponsor_explanation_category=expl,
        outcome_binary=outcome.binary,
        void_reason=outcome.void_reason,
        taxonomy_version=TAXONOMY_VERSION,
        recorded_at=now(),
        confirmed_by=prov.reviewer if prov.reviewer_kind == "human" else None,
        confirmed_recorded_at=now() if prov.reviewer_kind == "human" else None,
    )
    if conn.execute(
        select(resolutions.c.event_id).where(resolutions.c.event_id == event_id)
    ).first():
        conn.execute(update(resolutions).where(resolutions.c.event_id == event_id).values(**values))
    else:
        conn.execute(resolutions.insert().values(event_id=event_id, **values))
    status = (
        "void"
        if outcome.void_reason and outcome.void_reason != "not_scored_ledger_only"
        else "resolved"
    )
    conn.execute(
        update(events)
        .where(events.c.event_id == event_id)
        .values(status=status, updated_recorded_at=now())
    )
    return True


def apply_statement(
    conn: Connection, st: Statement, prov: Provenance, event_id: str | None = None
) -> ApplyResult:
    created = False
    if event_id is None:
        cands = candidate_events(conn, prov.sponsor_id, st)
        if len(cands) > 1:
            return ApplyResult(
                None,
                ambiguous=[
                    {
                        k: c[k]
                        for k in (
                            "event_id",
                            "asset_name",
                            "indication",
                            "nct_id",
                            "trial_name",
                            "status",
                        )
                    }
                    for c in cands
                ],
            )
        if cands:
            event_id = cands[0]["event_id"]
        else:
            event_id = create_event(conn, prov.sponsor_id, st)
            created = True
    _enrich_event(conn, event_id, st)
    passage = {"quote": st.quote} if st.quote else None
    valid_at = datetime.combine(st.event_date or prov.statement_date, datetime.min.time(), UTC)
    resolved = False
    match st.kind:
        case "guidance":
            add_promise(conn, event_id, st, prov)
        case "outcome" | "discontinuation":
            result = st.result_category or (
                "discontinued" if st.kind == "discontinuation" else None
            )
            for f, v in (
                ("result_category", result),
                ("result_subtype", st.result_subtype),
                ("sponsor_explanation_category", st.sponsor_explanation_category),
                ("event_date", (st.event_date or prov.statement_date).isoformat()),
                ("adcom_vote_held", st.adcom_vote_held if st.event_type == "adcom" else None),
            ):
                if v is not None:
                    add_label(conn, event_id, f, v, prov, valid_at, passage)
            resolved = resolve_event(conn, event_id, prov)
        case "cancellation":
            add_label(conn, event_id, "cancelled", True, prov, valid_at, passage)
            add_label(
                conn,
                event_id,
                "event_date",
                (st.event_date or prov.statement_date).isoformat(),
                prov,
                valid_at,
            )
            resolved = resolve_event(conn, event_id, prov, cancelled=True)
    return ApplyResult(event_id, created_event=created, resolved=resolved)

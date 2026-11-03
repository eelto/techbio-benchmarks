"""Two-model extraction, agreement, tie-break and routing.

Per document:
1. The free prefilter builds the excerpt (sources that fail it never reach a model).
2. Extractors A and B (two vendors, cheap tier, batch) each return statements.
3. Each statement's quote is checked against the document (ledger/quotes.py): exact and
   near-verbatim quotes are kept; the rest are dropped, and every check is logged in quote_checks
   with the claimed quote and the nearest source span (drop rate and a sample go in the summary).
4. Statements are paired across models by event type, asset and trial.
5. Routing per pair:
   - all compared fields agree, and reserved-field confidence >= tau -> auto-accept;
   - a non-reserved field disagrees, or only one model found the statement -> the tie-break model
     (third vendor) must pick A or B; "neither" goes to the queue;
   - a reserved field (result category, stop subtype, data trigger, explanation category) disagrees
     or has low confidence -> human queue. Models never break ties on reserved fields.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from importlib import resources
from typing import Any

from rich.console import Console
from sqlalchemy import Engine, select, update

from techbio.core.config import model_cfg
from techbio.core.db import extractions, now, review_queue, sources, sponsors
from techbio.core.ids import new_id
from techbio.core.ids import run_id as make_run_id
from techbio.core.llm import runner
from techbio.core.llm.cache import CompletionCache, LLMRequest, LLMResponse, cache_key
from techbio.core.spend import DryRun, SpendGuard
from techbio.ledger import prefilter
from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.names import assets_overlap
from techbio.ledger.quotes import QuoteMatch, match_quote, record_check
from techbio.ledger.scope import attribution, facts, readout_scope, registry_trial
from techbio.ledger.sources.ctgov import parse_study, stop_document
from techbio.ledger.taxonomy import (
    ALL_RESULTS,
    DATA_TRIGGERS,
    EXPLANATIONS,
    RESERVED_CONFIDENCE_TAU,
    RESERVED_FIELDS,
    STOP_SUBTYPES,
)
from techbio.ledger.timing import iso_or_none, parse_timing

console = Console(stderr=True)
PROMPT_VERSION = "extract_v1"
EXTRACTORS = ("extractor_a", "extractor_b")
TIEBREAK = "tiebreak"
TIEBREAK_REFERENCE = "tiebreak_reference"  # pilot only: checks the tie-breaker
RESERVED = RESERVED_FIELDS
COMPARED = ("kind", "phase", "application_kind", "nct_id", "window", "event_date", *RESERVED)
TIEBREAK_SHARE = 0.2  # planning assumption until the pilot measures it


def _nullable_enum(values: tuple[str, ...]) -> dict[str, Any]:
    # anyOf, not "type": ["string", "null"]: Anthropic rejects an enum value such as "2" under a
    # type list (every pilot request, 2026-10-31).
    return {"anyOf": [{"type": "string", "enum": list(values)}, {"type": "null"}]}


STATEMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "kind",
        "event_type",
        "asset_name",
        "asset_aliases",
        "indication",
        "nct_id",
        "trial_name",
        "phase",
        "application_kind",
        "timing_text",
        "timing_start",
        "timing_end",
        "event_date",
        "result_category",
        "result_subtype",
        "sponsor_explanation_category",
        "stop_data_trigger",
        "quote",
        "confidence",
    ],
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["guidance", "outcome", "discontinuation", "cancellation"],
        },
        "event_type": {
            "type": "string",
            "enum": ["readout", "fda_decision", "adcom", "discontinuation"],
        },
        "asset_name": {"type": "string"},
        "asset_aliases": {"type": "array", "items": {"type": "string"}},
        "indication": {"type": ["string", "null"]},
        "nct_id": {"type": ["string", "null"]},
        "trial_name": {"type": ["string", "null"]},
        "phase": _nullable_enum(("2", "2b", "2/3", "3")),
        "application_kind": _nullable_enum(("NDA", "BLA", "sNDA", "sBLA")),
        "timing_text": {"type": ["string", "null"]},
        "timing_start": {"type": ["string", "null"]},
        "timing_end": {"type": ["string", "null"]},
        "event_date": {"type": ["string", "null"]},
        "result_category": _nullable_enum(ALL_RESULTS),
        "result_subtype": _nullable_enum(STOP_SUBTYPES),
        "sponsor_explanation_category": _nullable_enum(EXPLANATIONS),
        "stop_data_trigger": _nullable_enum(DATA_TRIGGERS),
        "quote": {"type": "string"},
        "confidence": {"type": "number"},
    },
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statements"],
    "properties": {"statements": {"type": "array", "items": STATEMENT_SCHEMA}},
}
TB_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["choices"],
    "properties": {
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "choice", "quote"],
                "properties": {
                    "field": {"type": "string"},
                    "choice": {"type": "string", "enum": ["A", "B", "neither"]},
                    "quote": {"type": "string"},
                },
            },
        }
    },
}
TB_ADDENDUM = """

You are now the tie-breaker. Two independent extractors read the same document and disagree. For each disputed field listed, decide which candidate the document supports: "A", "B", or "neither" if the document supports neither value. The field "exists" asks whether the event statement in candidate A is supported by the document at all (B means no such statement should be reported). Quote the sentence that decides it, character-for-character. Judge only from the document."""


def system_prompt() -> str:
    return resources.files("techbio.ledger.prompts").joinpath(f"{PROMPT_VERSION}.md").read_text()


# --------------------------------------------------------------------------- documents


def document_text(src: dict[str, Any]) -> str:
    if src["type"] == "ctgov":
        with open(src["local_path"], "rb") as f:
            return stop_document(parse_study(json.loads(f.read())))
    return prefilter.load_text(src["local_path"], src["content_type"])


def run_prefilter(engine: Engine) -> dict[str, int]:
    stats = {"checked": 0, "pass": 0, "fail": 0, "deterministic": 0}
    with engine.connect() as conn:
        rows = (
            conn.execute(select(sources).where(sources.c.prefilter_status == "pending"))
            .mappings()
            .all()
        )
    for src in rows:
        stats["checked"] += 1
        if src["type"] == "fedreg_adcom":
            status, hits = "deterministic", None
        elif src["type"] == "ctgov":
            status, hits = ("pass" if src["meta"].get("stopped") else "fail"), None
        else:
            res = prefilter.run(document_text(dict(src)))
            status, hits = ("pass" if res.passed else "fail"), res.hits
        stats[status] += 1
        with engine.begin() as conn:
            conn.execute(
                update(sources)
                .where(sources.c.source_id == src["source_id"])
                .values(prefilter_status=status, prefilter_hits=hits)
            )
    return stats


@dataclass
class Doc:
    src: dict[str, Any]
    sponsor: dict[str, Any]
    excerpt: str
    full_text: str

    @property
    def statement_date(self) -> date:
        return (
            self.src["published_at"].date()
            if self.src["published_at"]
            else self.src["retrieved_at"].date()
        )


def pending_docs(
    engine: Engine, limit: int | None = None, source_ids: list[str] | None = None
) -> list[Doc]:
    q = (
        select(sources, sponsors.c.name.label("sponsor_name"), sponsors.c.tickers)
        .join(sponsors, sponsors.c.sponsor_id == sources.c.sponsor_id)
        .where(sources.c.prefilter_status == "pass", sources.c.extract_status == "none")
        .order_by(sources.c.published_at.desc())
    )
    if source_ids:
        q = q.where(sources.c.source_id.in_(source_ids))
    if limit:
        q = q.limit(limit)
    with engine.connect() as conn:
        rows = conn.execute(q).mappings().all()
    docs = []
    for r in rows:
        src = dict(r)
        text = document_text(src)
        excerpt = text if src["type"] == "ctgov" else prefilter.run(text).excerpt
        docs.append(Doc(src, {"name": r["sponsor_name"], "tickers": r["tickers"]}, excerpt, text))
    return docs


def user_message(doc: Doc) -> str:
    src = doc.src
    kind = {
        "edgar_8k": "SEC 8-K exhibit",
        "edgar_6k": "SEC 6-K exhibit",
        "ctgov": "ClinicalTrials.gov record",
    }.get(src["type"], src["type"])
    return (
        f"Sponsor: {doc.sponsor['name']} ({', '.join(doc.sponsor['tickers'])})\n"
        f"Document: {kind}, {src.get('title') or ''}, published {doc.statement_date.isoformat()}\n"
        f"URL: {src['url']}\n\n"
        f"<document>\n{doc.excerpt}\n</document>"
    )


def build_request(doc: Doc, model_key: str) -> LLMRequest:
    m = model_cfg(model_key)
    return LLMRequest(
        model_key=model_key,
        system=system_prompt(),
        user=user_message(doc),
        json_schema=SCHEMA,
        schema_name="catalyst_statements",
        max_output_tokens=int(m.get("max_output_tokens", 4000)),
        tag=doc.src["source_id"],
    )


# --------------------------------------------------------------------------- parsing and pairing


@dataclass
class Cand:
    model_key: str
    idx: int
    raw: dict[str, Any]
    st: Statement
    confidence: float
    qm: QuoteMatch

    @property
    def quote_ok(self) -> bool:
        return self.qm.accepted


def to_statement(raw: dict[str, Any], statement_date: date) -> Statement:
    window = parse_timing(raw.get("timing_text"), statement_date)
    if window is None and raw.get("timing_start") and raw.get("timing_end"):
        s, e = iso_or_none(raw["timing_start"]), iso_or_none(raw["timing_end"])
        if s and e and s <= e:
            window = (s, e, "day" if s == e else "range")
    return Statement(
        kind=raw["kind"],
        event_type="discontinuation" if raw["kind"] == "discontinuation" else raw["event_type"],
        asset_name=raw["asset_name"].strip(),
        asset_aliases=[a.strip() for a in raw.get("asset_aliases") or [] if a.strip()],
        indication=raw.get("indication"),
        nct_id=(raw.get("nct_id") or "").upper() or None,
        trial_name=raw.get("trial_name"),
        phase=raw.get("phase"),
        application_kind=raw.get("application_kind"),
        timing_text=raw.get("timing_text") if raw["kind"] == "guidance" else None,
        window_start=window[0] if window and raw["kind"] == "guidance" else None,
        window_end=window[1] if window and raw["kind"] == "guidance" else None,
        window_precision=window[2] if window and raw["kind"] == "guidance" else None,
        event_date=iso_or_none(raw.get("event_date")) if raw["kind"] != "guidance" else None,
        result_category=raw.get("result_category"),
        result_subtype=raw.get("result_subtype")
        if raw.get("result_category") == "stopped"
        else None,
        sponsor_explanation_category=raw.get("sponsor_explanation_category"),
        stop_data_trigger=raw.get("stop_data_trigger")
        if raw.get("result_category") == "stopped"
        else None,
        quote=raw.get("quote"),
    )


def parse_candidates(model_key: str, resp: LLMResponse | None, doc: Doc) -> list[Cand]:
    if resp is None or not resp.ok:
        return []
    try:
        items = resp.parsed()["statements"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []
    out = []
    for i, raw in enumerate(items):
        try:
            st = to_statement(raw, doc.statement_date)
        except (KeyError, AttributeError, TypeError):
            continue
        out.append(
            Cand(
                model_key,
                i,
                raw,
                st,
                float(raw.get("confidence") or 0.0),
                match_quote(raw.get("quote"), doc.full_text),
            )
        )
    return out


def same_event(a: Statement, b: Statement) -> bool:
    if a.event_type != b.event_type or not assets_overlap(a.names(), b.names()):
        return False
    if a.nct_id and b.nct_id and a.nct_id != b.nct_id:
        return False
    return not (
        a.trial_name
        and b.trial_name
        and a.trial_name.lower().replace("-", " ") != b.trial_name.lower().replace("-", " ")
    )


def pair(a: list[Cand], b: list[Cand]) -> list[tuple[Cand | None, Cand | None]]:
    out: list[tuple[Cand | None, Cand | None]] = []
    used: set[int] = set()
    for ca in a:
        match = next((cb for cb in b if cb.idx not in used and same_event(ca.st, cb.st)), None)
        if match:
            used.add(match.idx)
        out.append((ca, match))
    out.extend((None, cb) for cb in b if cb.idx not in used)
    return out


def field_value(st: Statement, f: str) -> Any:
    if f == "window":
        return (st.window_start, st.window_end) if st.window_start else None
    return getattr(st, f)


def disputed_fields(a: Statement, b: Statement) -> list[str]:
    out = []
    for f in COMPARED:
        va, vb = field_value(a, f), field_value(b, f)
        if f in ("nct_id", "event_date", "phase", "application_kind") and (
            va is None or vb is None
        ):
            continue  # one model left an optional field empty: take the stated one
        if va != vb:
            out.append(f)
    return out


def merge(a: Statement, b: Statement) -> Statement:
    """A's statement with B's values filling A's gaps (used only when they agree or after a pick)."""
    m = Statement.from_json(a.to_json())
    for f in ("indication", "nct_id", "trial_name", "phase", "application_kind", "event_date"):
        if getattr(m, f) is None and getattr(b, f) is not None:
            setattr(m, f, getattr(b, f))
    m.asset_aliases = sorted(set(a.asset_aliases) | set(b.names()) - {a.asset_name})
    return m


def set_field(st: Statement, f: str, src: Statement) -> None:
    if f == "window":
        st.window_start, st.window_end, st.window_precision, st.timing_text = (
            src.window_start,
            src.window_end,
            src.window_precision,
            src.timing_text,
        )
    else:
        setattr(st, f, getattr(src, f))


# --------------------------------------------------------------------------- the job


def _write_extraction_rows(
    conn, run: str, doc: Doc, cands: list[Cand], keys: dict[str, str]
) -> None:
    for c in cands:
        m = model_cfg(c.model_key)
        for f in (
            "kind",
            "event_type",
            "asset_name",
            "window",
            "event_date",
            "phase",
            "nct_id",
            *RESERVED,
        ):
            v = field_value(c.st, f)
            if isinstance(v, tuple):
                v = [x.isoformat() if x else None for x in v]
            elif isinstance(v, date):
                v = v.isoformat()
            conn.execute(
                extractions.insert().values(
                    extraction_id=new_id("ext"),
                    run_id=run,
                    source_id=doc.src["source_id"],
                    statement_idx=c.idx,
                    candidate_key=f"{c.st.event_type}|{c.st.asset_name}",
                    field=f,
                    value=v,
                    confidence=c.confidence,
                    quote=c.raw.get("quote"),
                    quote_verified=c.quote_ok,
                    model_key=c.model_key,
                    model_version=m["model_version"],
                    prompt_hash=keys[c.model_key + "_prompt"],
                    completion_key=keys[c.model_key],
                    created_recorded_at=now(),
                )
            )


def _queue(
    conn,
    doc: Doc,
    reason: str,
    field: str,
    payload: dict[str, Any],
    event_id: str | None = None,
    closed_by: str | None = None,
) -> None:
    """Open an item for the operator, or with `closed_by` record an automatic decision."""
    payload = {
        "source_id": doc.src["source_id"],
        "sponsor_id": doc.src["sponsor_id"],
        "statement_date": doc.statement_date.isoformat(),
        "url": doc.src["url"],
        **payload,
    }
    conn.execute(
        review_queue.insert().values(
            item_id=new_id("rq"),
            event_id=event_id,
            source_id=doc.src["source_id"],
            field=field,
            reason=reason,
            payload=payload,
            status="closed" if closed_by else "open",
            created_at=now(),
            closed_at=now() if closed_by else None,
            closed_by=closed_by,
        )
    )


Verdict = tuple[str, str, dict[str, Any] | None, str]  # (in | ask | out, why, trial, field)


def _scope(conn, doc: Doc, sts: list[Statement]) -> Verdict:
    """Attribution (R.1), then the 2b rule (ledger/scope.py). Each candidate is checked against its
    own trial and the most lenient verdict stands, so before routing a pair is dropped only when the
    registry rules out every candidate: one candidate's wrong NCT number cannot sink the other."""
    verdicts = [_scope_one(conn, doc, s) for s in sts]
    return min(verdicts, key=lambda v: LENIENCY.index(v[0]), default=("in", "", None, "phase"))


LENIENCY = ("in", "ask", "out")


def _scope_one(conn, doc: Doc, st: Statement) -> Verdict:
    if st.event_type != "readout":
        return "in", "", None, "phase"
    sponsor = doc.src["sponsor_id"]
    nct = st.nct_id or (doc.src["meta"].get("nct_id") if doc.src["type"] == "ctgov" else None)
    t = registry_trial(conn, sponsor, nct, st.trial_name, st.names())
    verdict, why = attribution(sponsor, st.names(), t)
    if verdict == "out":
        return verdict, why, t, "sponsor_id"
    return (*readout_scope(st.phase, t), t, "phase")


def _out_of_scope(conn, doc: Doc, st: Statement, verdict: Verdict, stats: dict[str, int]) -> None:
    """A readout the registry rules out never reaches the ledger; the drop stays on record."""
    _, why, t, field = verdict
    payload = {"statement": st.to_json(), "scope": why, "registry": facts(t)}
    _queue(conn, doc, "scope_check", field, payload, closed_by="auto:registry")
    stats["out_of_scope"] += 1


def _accept(
    conn, doc: Doc, st: Statement, reviewer: str, reviewer_kind: str, stats: dict[str, int]
) -> None:
    prov = Provenance(
        doc.src["source_id"], doc.src["sponsor_id"], doc.statement_date, reviewer, reviewer_kind
    )
    if doc.src["type"] == "ctgov" and not st.nct_id:
        st.nct_id = doc.src["meta"].get("nct_id")  # the registry record is that trial
    v = _scope(conn, doc, [st])
    verdict, why, t, field = v
    if verdict == "out":
        _out_of_scope(conn, doc, st, v, stats)
        return
    if verdict == "ask":
        payload = {
            "statement": st.to_json(),
            "reviewer": reviewer,
            "reviewer_kind": reviewer_kind,
            "scope": why,
            "registry": facts(t),
        }
        _queue(conn, doc, "scope_check", field, payload)
        stats["queued"] += 1
        return
    res = apply_statement(conn, st, prov)
    if res.ambiguous:
        _queue(
            conn,
            doc,
            "event_link_ambiguous",
            "event_id",
            {
                "statement": st.to_json(),
                "reviewer": reviewer,
                "reviewer_kind": reviewer_kind,
                "candidates": res.ambiguous,
            },
        )
        stats["queued"] += 1
        return
    stats["accepted"] += 1
    stats["events_created"] += int(res.created_event)
    stats["resolved"] += int(res.resolved)


def tiebreak_keys(compare: bool) -> tuple[str, ...]:
    return (TIEBREAK, TIEBREAK_REFERENCE) if compare else (TIEBREAK,)


def estimate_job(engine: Engine, docs: list[Doc], job_kind: str, compare_tiebreak: bool = False):
    cache = CompletionCache(engine)
    reqs = {k: [build_request(d, k) for d in docs] for k in EXTRACTORS}
    tb_n = math.ceil(len(docs) * TIEBREAK_SHARE)
    for k in tiebreak_keys(compare_tiebreak):
        reqs[k] = [build_request(d, k) for d in docs[:tb_n]]
    expected = {k: int(model_cfg(k).get("expected_output_tokens", 1500)) for k in reqs}
    est = runner.estimate(job_kind, reqs, cache, expected)
    est.notes.append(f"tie-break assumed for {TIEBREAK_SHARE:.0%} of documents")
    tps = model_cfg(TIEBREAK).get("output_tokens_per_s")
    if tps:
        hours = tb_n * expected[TIEBREAK] / tps / 3600
        est.notes.append(f"local tie-break, one call at a time: about {hours:.1f} h")
    return est


def run_extraction(
    engine: Engine,
    *,
    execute: bool,
    approval: str | None = None,
    limit: int | None = None,
    job_kind: str = "ledger_extract",
    source_ids: list[str] | None = None,
    compare_tiebreak: bool = False,
) -> dict[str, Any]:
    pf = run_prefilter(engine)
    docs = pending_docs(engine, limit, source_ids)
    run = make_run_id("ledger")
    console.print(f"prefilter: {pf}; documents to extract: {len(docs)}")
    if not docs:
        return {"prefilter": pf, "documents": 0}
    guard = SpendGuard(engine, job_kind, run, execute=execute, approval=approval)
    try:
        guard.authorize(estimate_job(engine, docs, job_kind, compare_tiebreak))
    except DryRun as e:
        console.print(f"[cyan]{e}[/]")
        return {
            "prefilter": pf,
            "documents": len(docs),
            "dry_run": True,
            "est_usd": guard.estimate.total_usd if guard.estimate else None,
        }

    status = "finished"
    stats = {
        "documents": len(docs),
        "accepted": 0,
        "queued": 0,
        "tiebreaks": 0,
        "events_created": 0,
        "resolved": 0,
        "quote_dropped": 0,
        "quote_fuzzy": 0,
        "out_of_scope": 0,
    }
    try:
        # A local tie-break server that is down must stop the job before the extractors spend.
        for k in tiebreak_keys(compare_tiebreak):
            runner.preflight(k)
        responses: dict[str, dict[str, LLMResponse]] = {}
        keys: dict[str, dict[str, str]] = {}
        for k in EXTRACTORS:
            m = model_cfg(k)
            reqs = [build_request(d, k) for d in docs]
            out = runner.run(engine, guard, k, reqs, run)
            _note_errors(stats, k, out)
            for d, r in zip(docs, reqs, strict=True):
                key = cache_key(r, m)
                keys.setdefault(d.src["source_id"], {})[k] = key
                keys[d.src["source_id"]][k + "_prompt"] = r.prompt_hash()
                if key in out:
                    responses.setdefault(d.src["source_id"], {})[k] = out[key]

        tb_jobs: list[tuple[Doc, Statement, Cand | None, Cand | None, list[str]]] = []
        for d in docs:
            sid = d.src["source_id"]
            got = {k: r for k, r in responses.get(sid, {}).items() if r.ok}
            if set(got) != set(EXTRACTORS):
                continue  # stopped by the cap or an error; the document stays pending
            ca = parse_candidates(EXTRACTORS[0], got[EXTRACTORS[0]], d)
            cb = parse_candidates(EXTRACTORS[1], got[EXTRACTORS[1]], d)
            with engine.begin() as conn:
                _write_extraction_rows(conn, run, d, ca + cb, keys[sid])
                for c in ca + cb:
                    record_check(
                        conn,
                        c.qm,
                        run_id=run,
                        source_id=sid,
                        model_key=c.model_key,
                        role="extractor",
                        claimed_quote=c.raw.get("quote"),
                        statement_idx=c.idx,
                        statement=c.st.to_json(),
                    )
                stats["quote_dropped"] += sum(1 for c in ca + cb if not c.quote_ok)
                stats["quote_fuzzy"] += sum(1 for c in ca + cb if c.qm.method == "fuzzy")
                for a, b in pair([c for c in ca if c.quote_ok], [c for c in cb if c.quote_ok]):
                    v = _scope(conn, d, [c.st for c in (a, b) if c])
                    if v[0] == "out":  # before any tie-break or operator time is spent
                        _out_of_scope(conn, d, (a or b).st, v, stats)
                        continue
                    if a and b:
                        disputed = disputed_fields(a.st, b.st)
                        reserved = [f for f in disputed if f in RESERVED]
                        has_reserved = any(field_value(a.st, f) is not None for f in RESERVED)
                        low_conf = (
                            has_reserved
                            and min(a.confidence, b.confidence) < RESERVED_CONFIDENCE_TAU
                        )
                        if reserved or low_conf:
                            _queue(
                                conn,
                                d,
                                "disagreement" if reserved else "low_confidence",
                                ",".join(
                                    reserved
                                    or [f for f in RESERVED if field_value(a.st, f) is not None]
                                ),
                                _payload(a, b),
                            )
                            stats["queued"] += 1
                        elif disputed:
                            tb_jobs.append((d, merge(a.st, b.st), a, b, disputed))
                        else:
                            _accept(
                                conn,
                                d,
                                merge(a.st, b.st),
                                f"auto-agreement:{a.model_key}+{b.model_key}",
                                "auto-agreement",
                                stats,
                            )
                    else:
                        lone = a or b
                        if any(field_value(lone.st, f) is not None for f in RESERVED):
                            # Only one model reported a result: a reserved-field disagreement.
                            _queue(conn, d, "disagreement", "exists", _payload(a, b))
                            stats["queued"] += 1
                        else:
                            tb_jobs.append((d, lone.st, lone, None, ["exists"]))
                conn.execute(
                    update(sources).where(sources.c.source_id == sid).values(extract_status="done")
                )

        if tb_jobs:
            stats["tiebreaks"] = len(tb_jobs)
            _run_tiebreaks(engine, guard, run, tb_jobs, stats, compare_tiebreak)
    except Exception:
        status = "failed"
        raise
    finally:
        summary = guard.finish(status)
    return {"prefilter": pf, **stats, "spend": summary}


def _note_errors(stats: dict[str, Any], model_key: str, out: dict[str, LLMResponse]) -> None:
    """Count a model's failed responses, with up to three distinct messages, in the job summary."""
    bad = [r.error for r in out.values() if not r.ok]
    if bad:
        stats.setdefault("errors", {})[model_key] = {
            "n": len(bad),
            "messages": list(dict.fromkeys(bad))[:3],
        }


def _payload(a: Cand | None, b: Cand | None) -> dict[str, Any]:
    return {
        "statement": (a or b).st.to_json(),
        "candidates": {
            "A": a.st.to_json() if a else None,
            "B": b.st.to_json() if b else None,
        },
        "models": {"A": a.model_key if a else None, "B": b.model_key if b else None},
        "confidence": {"A": a.confidence if a else None, "B": b.confidence if b else None},
        "quotes": {"A": a.raw.get("quote") if a else None, "B": b.raw.get("quote") if b else None},
    }


def _tiebreak_request(
    d: Doc, a: Cand | None, b: Cand | None, disputed: list[str], model_key: str
) -> LLMRequest:
    user = (
        user_message(d)
        + "\n\nCandidate A:\n"
        + json.dumps(a.st.to_json() if a else None, indent=1)
        + "\n\nCandidate B:\n"
        + json.dumps(b.st.to_json() if b else None, indent=1)
        + "\n\nDisputed fields: "
        + ", ".join(disputed)
    )
    return LLMRequest(
        model_key,
        system_prompt() + TB_ADDENDUM,
        user,
        TB_SCHEMA,
        "tiebreak",
        int(model_cfg(model_key).get("max_output_tokens", 6000)),
        tag=d.src["source_id"],
    )


def _choices(resp: LLMResponse | None) -> dict[str, str]:
    try:
        return {c["field"]: c["choice"] for c in resp.parsed()["choices"]}
    except (AttributeError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _run_tiebreaks(
    engine: Engine, guard: SpendGuard, run: str, jobs, stats: dict[str, int], compare: bool = False
) -> None:
    m = model_cfg(TIEBREAK)
    reqs = [_tiebreak_request(d, a, b, disputed, TIEBREAK) for d, _st, a, b, disputed in jobs]
    out = runner.run(engine, guard, TIEBREAK, reqs, run)
    _note_errors(stats, TIEBREAK, out)
    for (d, st, a, b, disputed), req in zip(jobs, reqs, strict=True):
        resp = out.get(cache_key(req, m))
        with engine.begin() as conn:
            if resp is None:
                _queue(
                    conn,
                    d,
                    "tiebreak_abstained",
                    ",".join(disputed),
                    {**_payload(a, b), "note": "tie-break not run (cap)"},
                )
                stats["queued"] += 1
                continue
            try:
                choices = {c["field"]: c for c in resp.parsed()["choices"]}
            except (json.JSONDecodeError, KeyError, TypeError):
                choices = {}
            final = Statement.from_json(st.to_json())
            ok = True
            for f in disputed:
                c = choices.get(f)
                if c is None or c["choice"] == "neither":
                    ok = False
                    break
                qm = match_quote(c.get("quote"), d.full_text)
                record_check(
                    conn,
                    qm,
                    run_id=run,
                    source_id=d.src["source_id"],
                    model_key=TIEBREAK,
                    role="tiebreak",
                    claimed_quote=c.get("quote"),
                    field=f,
                )
                if not qm.accepted:
                    ok = False
                    break
                if f == "exists":
                    ok = c["choice"] == "A"
                    continue
                set_field(final, f, (a if c["choice"] == "A" else b).st)
            if ok:
                _accept(
                    conn,
                    d,
                    final,
                    f"model-adjudicated:{m['model_version']}",
                    "model-adjudicated",
                    stats,
                )
            elif "exists" in disputed and choices.get("exists", {}).get("choice") == "B":
                stats["rejected_by_tiebreak"] = stats.get("rejected_by_tiebreak", 0) + 1
            else:
                _queue(
                    conn,
                    d,
                    "tiebreak_abstained",
                    ",".join(disputed),
                    {**_payload(a, b), "tiebreak": choices},
                )
                stats["queued"] += 1
    if compare:
        _compare_tiebreaks(engine, guard, run, jobs, reqs, out, stats)


def _compare_tiebreaks(engine: Engine, guard: SpendGuard, run: str, jobs, reqs, out, stats) -> None:
    """Pilot only: the reference model answers the same disputes, after the tie-breaker. Its
    choices are counted against the tie-breaker's and never applied. The summary carries choices
    only, never document text."""
    m, ref_m = model_cfg(TIEBREAK), model_cfg(TIEBREAK_REFERENCE)
    ref_reqs = [
        _tiebreak_request(d, a, b, disputed, TIEBREAK_REFERENCE) for d, _st, a, b, disputed in jobs
    ]
    ref_out = runner.run(engine, guard, TIEBREAK_REFERENCE, ref_reqs, run)
    _note_errors(stats, TIEBREAK_REFERENCE, ref_out)
    fields: dict[str, dict[str, int]] = {}
    disagreements = []
    for (d, _st, _a, _b, disputed), req, ref_req in zip(jobs, reqs, ref_reqs, strict=True):
        mine = _choices(out.get(cache_key(req, m)))
        theirs = _choices(ref_out.get(cache_key(ref_req, ref_m)))
        for f in disputed:
            n = fields.setdefault(f, {"n": 0, "agree": 0})
            n["n"] += 1
            if mine.get(f) is not None and mine.get(f) == theirs.get(f):
                n["agree"] += 1
            else:
                disagreements.append(
                    {
                        "source_id": d.src["source_id"],
                        "field": f,
                        "tiebreak": mine.get(f),
                        "reference": theirs.get(f),
                    }
                )
    stats["tiebreak_comparison"] = {
        "reference": ref_m["model_version"],
        "fields": fields,
        "disagreements": disagreements,
    }

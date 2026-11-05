"""Two-model extraction, agreement, tie-break and routing.

Per document:
1. The free prefilter builds the excerpt (sources that fail it never reach a model).
2. Extractors A and B (two vendors, cheap tier, batch) each return statements.
3. Each statement's quote is checked against the document (ledger/quotes.py): exact and
   near-verbatim quotes are kept; the rest are dropped, and every check is logged in quote_checks
   with the claimed quote and the nearest source span (drop rate and a sample go in the summary).
4. Each model's repeats of one event collapse into one statement. Statements are then paired across
   models by event type, asset, trial and disease, best match first. Partner mentions (another
   company's trial or application, decision R.1) are counted and kept, and never paired or routed.
5. Routing per pair:
   - all compared fields agree -> auto-accept (V.1, 2026-11-05: the models' self-ratings are
     stored but route nothing; a random audit of agreed outcomes checks this path, V.2);
   - a non-reserved field disagrees, or only one model found the statement -> the tie-break model
     (third vendor) must pick A or B; "neither" goes to the queue;
   - a reserved field (result category, stop subtype, data trigger, explanation category)
     disagrees -> human queue. Models never break ties on reserved fields.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property
from importlib import resources
from typing import Any

from rich.console import Console
from sqlalchemy import Engine, select, update

from techbio.core.config import model_cfg
from techbio.core.db import extractions, now, review_queue, sources, sponsors, trials
from techbio.core.ids import new_id
from techbio.core.ids import run_id as make_run_id
from techbio.core.llm import runner
from techbio.core.llm.cache import CompletionCache, LLMRequest, LLMResponse, cache_key
from techbio.core.spend import DryRun, SpendGuard
from techbio.ledger import prefilter
from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.names import (
    assets_overlap,
    indications_agree,
    indications_conflict,
    same_company,
)
from techbio.ledger.quotes import QuoteMatch, match_quote, record_check
from techbio.ledger.scope import (
    LEDGER_START,
    attribution,
    facts,
    readout_scope,
    registry_stop_date,
    registry_trial,
)
from techbio.ledger.sources.ctgov import parse_study, stop_document
from techbio.ledger.taxonomy import (
    ALL_RESULTS,
    DATA_TRIGGERS,
    EXPLANATIONS,
    RESERVED_FIELDS,
    STOP_SUBTYPES,
)
from techbio.ledger.timing import iso_or_none, parse_timing

console = Console(stderr=True)
PROMPT_VERSION = "extract_v2"  # v1 until 2026-11-03; v2 adds the pilot's fixes and partner mentions
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
PARTNER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["asset_name", "event_type", "trial_name", "nct_id", "run_by", "quote"],
    "properties": {
        "asset_name": {"type": "string"},
        "event_type": STATEMENT_SCHEMA["properties"]["event_type"],
        "trial_name": {"type": ["string", "null"]},
        "nct_id": {"type": ["string", "null"]},
        "run_by": {"type": ["string", "null"]},
        "quote": {"type": "string"},
    },
}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["statements", "partner_mentions"],
    "properties": {
        "statements": {"type": "array", "items": STATEMENT_SCHEMA},
        "partner_mentions": {"type": "array", "items": PARTNER_SCHEMA},
    },
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

You are now the tie-breaker. Two independent extractors read the same document and disagree. For each disputed field listed, decide which candidate the document supports: "A", "B", or "neither" if the document supports neither value. The field "exists" asks whether the event statement in candidate A should be reported at all: B means it should not, because the document does not support it or the rules above put it out of scope. Quote the sentence that decides it, character-for-character. Judge only from the document."""


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

    @cached_property
    def document_date(self) -> date | None:
        """The date the document carries, for outcomes the extractors leave undated."""
        return (
            None if self.src["type"] == "ctgov" else dateline(self.full_text, self.statement_date)
        )


_MONTH = (
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_DATE = re.compile(
    rf"\b(?:{_MONTH}\s+(\d{{1,2}}),?\s+(\d{{4}})|(?<![\d.])(\d{{1,2}})\s+{_MONTH}\s+(\d{{4}}))\b",
    re.I,
)
# A balance or period date ("cash as of June 30", "the quarter ended September 30") is not a release
# date, however close to the filing.
_NOT_A_DATELINE = re.compile(r"(?:as\s+of|ended|ending|through)\s*$", re.I)
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DATELINE_CHARS = 1500  # a release's dateline follows its headline
# Measured on the pool (2026-11-05): 87% of datelines are the filing day and 9% one to four days
# earlier (a 6-K trails its release). Past two weeks, the dates found were period ends and slide
# page numbers.
DATELINE_DAYS = 14


def dateline(text: str, filed: date) -> date | None:
    """The first date near the top of a document that could be its release date: on or before the
    filing date and at most two weeks earlier (run 7: Sanofi's COAST 1, released 2026-03-28 and
    filed 2026-03-31). A later date is an upcoming event; an earlier one is something else."""
    head = text[:DATELINE_CHARS]
    for m in _DATE.finditer(head):
        if _NOT_A_DATELINE.search(head[max(0, m.start() - 20) : m.start()]):
            continue
        month, day, year = (m[1], m[2], m[3]) if m[1] else (m[5], m[4], m[6])
        try:
            d = date(int(year), _MONTHS.index(month[:3].lower()) + 1, int(day))
        except ValueError:
            continue
        if filed - timedelta(days=DATELINE_DAYS) <= d <= filed:
            return d
    return None


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
    return _docs(engine, q)


def docs_by_id(engine: Engine, source_ids: list[str]) -> list[Doc]:
    """Documents already extracted, for a tie-break that has to be asked again."""
    q = (
        select(sources, sponsors.c.name.label("sponsor_name"), sponsors.c.tickers)
        .join(sponsors, sponsors.c.sponsor_id == sources.c.sponsor_id)
        .where(sources.c.source_id.in_(source_ids))
    )
    return _docs(engine, q)


def _docs(engine: Engine, q) -> list[Doc]:
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


Mention = tuple[dict[str, Any], str | None, QuoteMatch]  # (fields, claimed quote, check)
MENTION_FIELDS = ("asset_name", "event_type", "trial_name", "nct_id", "run_by")


def parse_partner_mentions(resp: LLMResponse | None, doc: Doc) -> list[Mention]:
    """Another company's trial or application named in the document (prompt v2, decision R.1).
    Kept to measure what R.1 leaves out; never a statement."""
    try:
        items = resp.parsed().get("partner_mentions") or []
    except (AttributeError, json.JSONDecodeError, TypeError):
        return []
    return [
        (
            {f: m.get(f) for f in MENTION_FIELDS},
            m.get("quote"),
            match_quote(m.get("quote"), doc.full_text),
        )
        for m in items
        if isinstance(m, dict) and m.get("asset_name")
    ]


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


def match_score(a: Statement, b: Statement) -> int | None:
    """How strongly two statements describe one event; None when they cannot. Two clearly different
    diseases never match, even under one NCT number (pilot run 3, case 5: one extractor gave a
    sickle cell readout the LR-MDS trial's number)."""
    if not same_event(a, b) or indications_conflict(a.indication, b.indication):
        return None
    return (
        8 * bool(a.nct_id and a.nct_id == b.nct_id)
        + 4 * bool(a.trial_name and b.trial_name)  # same_event has checked that they agree
        + 2 * indications_agree(a.indication, b.indication)
        + (a.kind == b.kind)
        + (field_value(a, "window") == field_value(b, "window"))
    )


def pair(a: list[Cand], b: list[Cand]) -> list[tuple[Cand | None, Cand | None]]:
    """Strongest matches first, so a statement is not taken by a weaker partner it happens to
    precede. Ties keep document order."""
    scored = sorted(
        (-s, i, j)
        for i, ca in enumerate(a)
        for j, cb in enumerate(b)
        if (s := match_score(ca.st, cb.st)) is not None
    )
    a_to_b: dict[int, int] = {}
    for _, i, j in scored:
        if i not in a_to_b and j not in a_to_b.values():
            a_to_b[i] = j
    out: list[tuple[Cand | None, Cand | None]] = [
        (ca, b[a_to_b[i]] if i in a_to_b else None) for i, ca in enumerate(a)
    ]
    out.extend((None, cb) for j, cb in enumerate(b) if j not in a_to_b.values())
    return out


def collapse_duplicates(cands: list[Cand]) -> list[Cand]:
    """One model's repeats of one event (the text, a table, a summary list) become one candidate,
    with gaps filled from the repeats. Repeats that differ in any compared field stay apart, so the
    disagreement still reaches routing (pilot: Vor Bio, one readout reported three times)."""
    kept: list[Cand] = []
    for c in cands:
        dup = next(
            (
                k
                for k in kept
                if match_score(k.st, c.st) is not None and not disputed_fields(k.st, c.st)
            ),
            None,
        )
        if dup is None:
            kept.append(c)
        else:
            dup.st = merge(dup.st, c.st)
    return kept


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


def _write_partner_rows(
    conn, run: str, doc: Doc, mentions: dict[str, list[Mention]], keys: dict[str, str]
) -> None:
    for model_key, found in mentions.items():
        m = model_cfg(model_key)
        for i, (value, quote, qm) in enumerate(found):
            conn.execute(
                extractions.insert().values(
                    extraction_id=new_id("ext"),
                    run_id=run,
                    source_id=doc.src["source_id"],
                    statement_idx=i,
                    candidate_key=f"partner|{value['asset_name']}",
                    field="partner_mention",
                    value=value,
                    quote=quote,
                    quote_verified=qm.accepted,
                    model_key=model_key,
                    model_version=m["model_version"],
                    prompt_hash=keys[model_key + "_prompt"],
                    completion_key=keys[model_key],
                    created_recorded_at=now(),
                )
            )


def _count_partner_mentions(
    stats: dict[str, Any], mentions: dict[str, list[Mention]], universe: list[str]
) -> None:
    """Per model, quote-verified mentions by whether the company named as running the trial is in
    the universe (its own filings carry the event) or not (R.1 leaves it out). Matching is by name,
    so a short form the matcher misses ("Lilly") counts as outside."""
    for model_key, found in mentions.items():
        n = stats["partner_mentions"][model_key]
        for value, _quote, qm in found:
            if not qm.accepted:
                continue
            n["n"] += 1
            run_by = value.get("run_by")
            if not run_by:
                n["run_by_not_stated"] += 1
            elif any(same_company(run_by, name) for name in universe):
                n["in_universe"] += 1
            else:
                n["outside_universe"] += 1


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
        "document_date": doc.document_date.isoformat() if doc.document_date else None,
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
    if st.kind != "guidance" and st.event_date and st.event_date < LEDGER_START:
        return "out", f"dated before the ledger's start ({LEDGER_START})", None, "event_date"
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
    by = "auto:scope" if field == "event_date" else "auto:registry"
    _queue(conn, doc, "scope_check", field, payload, closed_by=by)
    stats["out_of_scope"] += 1


def _date_registry_stops(conn, doc: Doc, cands: list[Cand]) -> None:
    """A CT.gov stop happened when the registry says the trial ended, not when its record was last
    edited (2026-11-05: NCT05074420 ended 2024-09-05 and was stored as a 2026-08-11 stop). Both
    candidates take the registry's date, so it never splits a pair."""
    nct = doc.src["meta"].get("nct_id")
    t = (
        conn.execute(select(trials).where(trials.c.nct_id == nct)).mappings().first()
        if nct
        else None
    )
    stop = registry_stop_date(dict(t) if t else None)
    if stop:
        for c in cands:
            if c.st.result_category == "stopped":
                c.st.event_date = stop


def _accept(
    conn, doc: Doc, st: Statement, reviewer: str, reviewer_kind: str, stats: dict[str, int]
) -> None:
    prov = Provenance(
        doc.src["source_id"],
        doc.src["sponsor_id"],
        doc.statement_date,
        reviewer,
        reviewer_kind,
        document_date=doc.document_date,
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


def estimate_job(
    engine: Engine,
    docs: list[Doc],
    job_kind: str,
    compare_tiebreak: bool = False,
    retries: list[tuple[Any, dict[str, Any]]] = (),
):
    cache = CompletionCache(engine)
    reqs = {k: [build_request(d, k) for d in docs] for k in EXTRACTORS}
    tb_n = math.ceil(len(docs) * TIEBREAK_SHARE)
    for k in tiebreak_keys(compare_tiebreak):
        reqs[k] = [build_request(d, k) for d in docs[:tb_n]]
    reqs[TIEBREAK] += [
        _tiebreak_request(d, a, b, disp, TIEBREAK) for (d, _, a, b, disp), _ in retries
    ]
    expected = {k: int(model_cfg(k).get("expected_output_tokens", 1500)) for k in reqs}
    est = runner.estimate(job_kind, reqs, cache, expected)
    est.notes.append(f"tie-break assumed for {TIEBREAK_SHARE:.0%} of documents")
    if retries:
        est.notes.append(f"{len(retries)} failed tie-break(s) asked again")
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
    retries = [r for r in retry_jobs(engine) if not source_ids or r[1]["source_id"] in source_ids]
    run = make_run_id("ledger")
    console.print(
        f"prefilter: {pf}; documents to extract: {len(docs)}; tie-breaks to retry: {len(retries)}"
    )
    if not docs and not retries:
        return {"prefilter": pf, "documents": 0}
    guard = SpendGuard(engine, job_kind, run, execute=execute, approval=approval)
    try:
        guard.authorize(estimate_job(engine, docs, job_kind, compare_tiebreak, retries))
    except DryRun as e:
        console.print(f"[cyan]{e}[/]")
        return {
            "prefilter": pf,
            "documents": len(docs),
            "tiebreak_retries": len(retries),
            "dry_run": True,
            "est_usd": guard.estimate.total_usd if guard.estimate else None,
        }

    status = "finished"
    stats = {
        "documents": len(docs),
        "accepted": 0,
        "queued": 0,
        "tiebreaks": 0,
        "tiebreak_retries": len(retries),
        "events_created": 0,
        "resolved": 0,
        "quote_dropped": 0,
        "quote_fuzzy": 0,
        "out_of_scope": 0,
        "duplicates_collapsed": 0,
        "partner_mentions": {
            k: {"n": 0, "in_universe": 0, "outside_universe": 0, "run_by_not_stated": 0}
            for k in EXTRACTORS
        },
    }
    with engine.connect() as conn:
        universe = list(conn.execute(select(sponsors.c.name)).scalars())
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
            mentions = {k: parse_partner_mentions(got[k], d) for k in EXTRACTORS}
            with engine.begin() as conn:
                _write_extraction_rows(conn, run, d, ca + cb, keys[sid])
                _write_partner_rows(conn, run, d, mentions, keys[sid])
                _count_partner_mentions(stats, mentions, universe)
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
                verified = [[c for c in cands if c.quote_ok] for cands in (ca, cb)]
                a_ok, b_ok = (collapse_duplicates(cands) for cands in verified)
                stats["duplicates_collapsed"] += sum(map(len, verified)) - len(a_ok) - len(b_ok)
                if d.src["type"] == "ctgov":
                    _date_registry_stops(conn, d, a_ok + b_ok)
                for a, b in pair(a_ok, b_ok):
                    v = _scope(conn, d, [c.st for c in (a, b) if c])
                    if v[0] == "out":  # before any tie-break or operator time is spent
                        _out_of_scope(conn, d, (a or b).st, v, stats)
                        continue
                    if a and b:
                        disputed = disputed_fields(a.st, b.st)
                        reserved = [f for f in disputed if f in RESERVED]
                        if reserved:
                            _queue(conn, d, "disagreement", ",".join(reserved), _payload(a, b))
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

        jobs = tb_jobs + [j for j, _ in retries]
        if jobs:
            stats["tiebreaks"] = len(jobs)
            retry_of = {len(tb_jobs) + n: item for n, (_, item) in enumerate(retries)}
            _run_tiebreaks(engine, guard, run, jobs, stats, compare_tiebreak, retry_of)
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


TIEBREAK_TRIES = 3  # in all; then the dispute stays with the operator
_FAILED = ("tie-break failed", "tie-break not run")


def retry_jobs(engine: Engine) -> list[tuple[Any, dict[str, Any]]]:
    """Tie-breaks that failed or never ran (a refused batch, a crash, the cap), each with the queue
    item holding it, to be asked again on the next run (2026-11-05). A model's own "neither" is a
    decision and stays with the operator, as does a dispute that has failed TIEBREAK_TRIES times."""
    with engine.connect() as conn:
        items = [
            dict(i)
            for i in conn.execute(
                select(review_queue)
                .where(
                    review_queue.c.status == "open",
                    review_queue.c.reason == "tiebreak_abstained",
                )
                .order_by(review_queue.c.created_at)
            ).mappings()
            if str(i["payload"].get("note", "")).startswith(_FAILED)
            and i["payload"].get("attempts", 1) < TIEBREAK_TRIES
        ]
    if not items:
        return []
    docs = {d.src["source_id"]: d for d in docs_by_id(engine, [i["source_id"] for i in items])}
    out = []
    for i in items:
        p, d = i["payload"], docs.get(i["source_id"])
        if d is None:
            continue
        a, b = _cand(p, "A"), _cand(p, "B")
        st = merge(a.st, b.st) if a and b else (a or b).st
        out.append(((d, st, a, b, i["field"].split(",")), i))
    return out


def _cand(p: dict[str, Any], slot: str) -> Cand | None:
    """A candidate rebuilt from a queue item: as much of it as a tie-break uses (its quote check is
    on record from the run that found it)."""
    if p["candidates"][slot] is None:
        return None
    st = Statement.from_json(p["candidates"][slot])
    conf = p["confidence"][slot] or 0.0
    return Cand(p["models"][slot], 0, {"quote": p["quotes"][slot]}, st, conf, None)


def _run_tiebreaks(
    engine: Engine,
    guard: SpendGuard,
    run: str,
    jobs,
    stats: dict[str, int],
    compare: bool = False,
    retry_of: dict[int, dict[str, Any]] | None = None,
) -> None:
    m = model_cfg(TIEBREAK)
    reqs = [_tiebreak_request(d, a, b, disputed, TIEBREAK) for d, _st, a, b, disputed in jobs]
    retry_of = retry_of or {}

    def tried(conn, n: int) -> dict[str, Any]:
        """Close the queue item job n was retried from; the try count for any item it opens."""
        old = retry_of.get(n)
        if old is None:
            return {}
        conn.execute(
            update(review_queue)
            .where(review_queue.c.item_id == old["item_id"])
            .values(status="closed", closed_at=now(), closed_by="auto:retry")
        )
        return {"attempts": old["payload"].get("attempts", 1) + 1}

    try:
        out = runner.run(engine, guard, TIEBREAK, reqs, run)
    except Exception as e:
        # The documents are already marked done, so a dispute not queued here would be lost
        # (2026-11-04). Queue every one, then fail the job.
        with engine.begin() as conn:
            for n, (d, _st, a, b, disputed) in enumerate(jobs):
                note = f"tie-break not run: {type(e).__name__}"
                _queue(
                    conn,
                    d,
                    "tiebreak_abstained",
                    ",".join(disputed),
                    {**_payload(a, b), "note": note, **tried(conn, n)},
                )
        stats["queued"] += len(jobs)
        raise
    _note_errors(stats, TIEBREAK, out)
    for n, ((d, st, a, b, disputed), req) in enumerate(zip(jobs, reqs, strict=True)):
        resp = out.get(cache_key(req, m))
        with engine.begin() as conn:
            again = tried(conn, n)
            if resp is None:
                _queue(
                    conn,
                    d,
                    "tiebreak_abstained",
                    ",".join(disputed),
                    {**_payload(a, b), "note": "tie-break not run (cap)", **again},
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
                # A failed answer is not the model declining: say so to the operator.
                failed = {} if resp.ok else {"note": f"tie-break failed: {resp.error}"}
                _queue(
                    conn,
                    d,
                    "tiebreak_abstained",
                    ",".join(disputed),
                    {**_payload(a, b), "tiebreak": choices, **failed, **again},
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

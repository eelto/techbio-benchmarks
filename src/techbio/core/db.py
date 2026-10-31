"""Database schema (SQLAlchemy Core) and engine helpers.

The schema is portable: SQLite now, Postgres later. Times are stored as UTC and always come back
timezone-aware. Ledger and shared tables live here; arena and harness tables arrive with their
milestones, each through an Alembic migration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.types import TypeDecorator

from techbio.core.config import settings


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend (SQLite drops tzinfo otherwise)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; all stored times must be UTC-aware")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


TS = UTCDateTime

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

EVENT_TYPES = ("readout", "fda_decision", "adcom", "discontinuation")
DATE_TYPES = ("dated", "fuzzy")
EVENT_STATUS = ("open", "resolved", "void", "excluded")
REVIEWER_KINDS = ("human", "model-adjudicated", "auto-agreement", "deterministic")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


# --------------------------------------------------------------------------- ledger

sponsors = Table(
    "sponsors",
    metadata,
    Column("sponsor_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("cik", Integer, nullable=False, unique=True),
    Column("tickers", JSON, nullable=False),
    Column("exchange", String),
    Column("filer_kind", String),  # domestic | fpi
    Column("sic", Integer),
    Column("in_universe_from", Date),
    Column("in_universe_to", Date),
    Column("created_recorded_at", TS, nullable=False),
    Column("updated_recorded_at", TS, nullable=False),
)

programs = Table(
    "programs",
    metadata,
    Column("program_id", String, primary_key=True),
    Column("sponsor_id", String, ForeignKey("sponsors.sponsor_id"), nullable=False),
    Column("asset_name", String, nullable=False),
    Column("aliases", JSON, nullable=False),
    Column("indication", String),
    Column("modality", String),
    Column("target", String),
    Column("mechanism", String),
    Column("created_recorded_at", TS, nullable=False),
)

sources = Table(
    "sources",
    metadata,
    Column("source_id", String, primary_key=True),
    Column("url", Text, nullable=False),
    Column("type", String, nullable=False),
    Column("sponsor_id", String, ForeignKey("sponsors.sponsor_id")),
    Column("is_primary", Boolean, nullable=False),
    Column("title", Text),
    Column("published_at", TS),
    Column("retrieved_at", TS, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("local_path", Text, nullable=False),  # into gitignored data/raw/
    Column("content_type", String),
    Column("meta", JSON, nullable=False),
    Column("prefilter_status", String, nullable=False, default="pending"),  # pending|pass|fail
    Column("prefilter_hits", JSON),
    Column("extract_status", String, nullable=False, default="none"),  # none|done|failed
    Column("created_recorded_at", TS, nullable=False),
    UniqueConstraint("url", "sha256", name="uq_sources_url_sha"),
    CheckConstraint(
        _in(
            "type",
            (
                "edgar_8k",
                "edgar_6k",
                "ctgov",
                "fedreg_adcom",
                "drugsfda",
                "fda_press",
                "fda_crl",
                "ir_page",
                "market",
            ),
        ),
        name="type",
    ),
)
Index("ix_sources_sponsor_pub", sources.c.sponsor_id, sources.c.published_at)

trials = Table(
    "trials",
    metadata,
    Column("nct_id", String, primary_key=True),
    Column("sponsor_id", String, ForeignKey("sponsors.sponsor_id")),
    Column("program_id", String, ForeignKey("programs.program_id")),
    Column("lead_sponsor_name", String),
    Column("brief_title", Text),
    Column("acronym", String),
    Column("phases", JSON, nullable=False),
    Column("allocation", String),
    Column("masking", String),
    Column("enrollment", Integer),
    Column("enrollment_type", String),  # ACTUAL | ESTIMATED
    Column("overall_status", String),
    Column("why_stopped", Text),
    Column("primary_completion_date", String),  # CT.gov partial dates ("2027-03") kept as given
    Column("primary_completion_type", String),  # ACTUAL | ESTIMATED
    Column("conditions", JSON),
    Column("interventions", JSON),
    Column("primary_outcomes", JSON),
    Column("last_update_posted", Date),
    Column("source_id", String, ForeignKey("sources.source_id"), nullable=False),
    Column("created_recorded_at", TS, nullable=False),
    Column("updated_recorded_at", TS, nullable=False),
)

events = Table(
    "events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("event_type", String, nullable=False),
    # Derived cache: 'dated' if the latest promise has day precision. As-of reads use promises.
    Column("date_type", String, nullable=False),
    Column("sponsor_id", String, ForeignKey("sponsors.sponsor_id"), nullable=False),
    Column("program_id", String, ForeignKey("programs.program_id")),
    Column("asset_name", String, nullable=False),
    Column("asset_aliases", JSON, nullable=False),
    Column("indication", Text),
    Column("nct_id", String),
    Column("trial_name", String),
    Column("phase", String),
    Column("application_no", String),
    Column("application_kind", String),  # NDA | BLA | sNDA | sBLA
    Column("status", String, nullable=False, default="open"),
    Column("dedup_key", String, nullable=False, unique=True),
    Column("created_recorded_at", TS, nullable=False),
    Column("updated_recorded_at", TS, nullable=False),
    CheckConstraint(_in("event_type", EVENT_TYPES), name="event_type"),
    CheckConstraint(_in("date_type", DATE_TYPES), name="date_type"),
    CheckConstraint(_in("status", EVENT_STATUS), name="status"),
)

labels = Table(
    "labels",
    metadata,
    Column("label_id", String, primary_key=True),
    Column("event_id", String, ForeignKey("events.event_id"), nullable=False),
    Column("field", String, nullable=False),
    Column("value", JSON),
    Column("reviewer", String, nullable=False),
    Column("reviewer_kind", String, nullable=False),
    Column("version", Integer, nullable=False),
    Column("valid_at", TS),  # when the fact became true in the world (e.g. topline date)
    Column("recorded_at", TS, nullable=False),  # when we recorded it; append-only
    Column("supersedes_label_id", String, ForeignKey("labels.label_id")),
    Column("note", Text),
    UniqueConstraint("event_id", "field", "version", name="uq_labels_event_field_version"),
    CheckConstraint(_in("reviewer_kind", REVIEWER_KINDS), name="reviewer_kind"),
)

label_sources = Table(
    "label_sources",
    metadata,
    Column("label_id", String, ForeignKey("labels.label_id"), primary_key=True),
    Column("source_id", String, ForeignKey("sources.source_id"), primary_key=True),
    Column("passage_ref", JSON),  # {"quote": ..., "start": int, "end": int}; never exported
)

promises = Table(
    "promises",
    metadata,
    Column("promise_id", String, primary_key=True),
    Column("event_id", String, ForeignKey("events.event_id"), nullable=False),
    Column("statement_date", Date, nullable=False),  # publication date of the guiding source
    Column("guided_text", Text, nullable=False),  # "mid-2027", "PDUFA date of March 15, 2027"
    Column("guided_start", Date, nullable=False),
    Column("guided_end", Date, nullable=False),
    Column("guided_precision", String, nullable=False),  # day|month|quarter|half|year|range
    Column("source_id", String, ForeignKey("sources.source_id"), nullable=False),
    Column("reviewer_kind", String, nullable=False),
    Column("recorded_at", TS, nullable=False),
    UniqueConstraint("event_id", "source_id", name="uq_promises_event_source"),
    CheckConstraint("guided_start <= guided_end", name="window_order"),
)

extractions = Table(
    "extractions",
    metadata,
    Column("extraction_id", String, primary_key=True),
    Column("run_id", String, nullable=False),
    Column("source_id", String, ForeignKey("sources.source_id"), nullable=False),
    Column("statement_idx", Integer, nullable=False),
    Column("candidate_key", String),
    Column("event_id", String, ForeignKey("events.event_id")),
    Column("field", String, nullable=False),
    Column("value", JSON),
    Column("confidence", Float),
    Column("quote", Text),
    Column("quote_verified", Boolean, nullable=False),
    Column("model_key", String, nullable=False),
    Column("model_version", String, nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("completion_key", String(64), ForeignKey("completions.cache_key"), nullable=False),
    Column("created_recorded_at", TS, nullable=False),
)

review_queue = Table(
    "review_queue",
    metadata,
    Column("item_id", String, primary_key=True),
    Column("event_id", String, ForeignKey("events.event_id")),
    Column("source_id", String, ForeignKey("sources.source_id")),
    Column("field", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("payload", JSON, nullable=False),  # candidate values, quotes, confidences
    Column("status", String, nullable=False, default="open"),  # open | closed | skipped
    Column("created_at", TS, nullable=False),
    Column("closed_at", TS),
    Column("closed_by", String),
    Column("closed_label_id", String, ForeignKey("labels.label_id")),
    CheckConstraint(
        _in(
            "reason",
            (
                "disagreement",
                "low_confidence",
                "quote_unverified",
                "event_link_ambiguous",
                "tiebreak_abstained",
                "operator_flag",
                "outcome_confirmation",
                "parse_failed",
                "exclusion_link",
            ),
        ),
        name="reason",
    ),
)

resolutions = Table(
    "resolutions",
    metadata,
    Column("event_id", String, ForeignKey("events.event_id"), primary_key=True),
    Column("label_id", String, ForeignKey("labels.label_id"), nullable=False),
    # S9: every resolution names a primary source. Enforced by the schema, not just by code.
    Column("primary_source_id", String, ForeignKey("sources.source_id"), nullable=False),
    Column("event_date", Date, nullable=False),
    Column("result_category", String),  # NULL only for voids with no result (e.g. cancelled)
    Column("result_subtype", String),
    # The ledger's category (taxonomy.explanation_category); the sponsor's stated one is kept too.
    Column("sponsor_explanation_category", String),
    Column("stated_explanation_category", String),
    Column("stop_data_trigger", String),  # interim_analysis | futility | dsmb_recommendation
    Column("enrolled_at_stop", Integer),  # CT.gov actual enrollment, for stopped readouts
    Column("scored_as", String),  # the result the binary scores; "missed" for data-triggered stops
    Column("outcome_binary", Integer),  # 1 | 0 | NULL when void
    Column("void_reason", String),
    Column("taxonomy_version", String, nullable=False),
    Column("recorded_at", TS, nullable=False),
    Column("confirmed_by", String),  # B7: operator confirms every arena-scored outcome
    Column("confirmed_recorded_at", TS),
    CheckConstraint("(outcome_binary IS NULL) = (void_reason IS NOT NULL)", name="void_xor_binary"),
    CheckConstraint(
        "result_category IS NOT NULL OR void_reason IS NOT NULL", name="result_or_void"
    ),
)

exclusions = Table(
    "exclusions",
    metadata,
    # Registry records that are not events (taxonomy v1.1): withdrawn before enrollment, or withdrawn
    # citing another trial's data (linked to that trial). Exported with reasons and links only.
    Column("exclusion_id", String, primary_key=True),
    Column("nct_id", String, nullable=False, unique=True),
    Column("sponsor_id", String, ForeignKey("sponsors.sponsor_id")),
    Column("source_id", String, ForeignKey("sources.source_id"), nullable=False),
    Column("reason", String, nullable=False),
    Column("enrolled", Integer),
    Column("linked_nct_id", String),
    Column("linked_by", String),  # parser:<version> | human:<id>
    Column("linked_recorded_at", TS),
    Column("taxonomy_version", String, nullable=False),
    Column("recorded_at", TS, nullable=False),
    CheckConstraint(
        _in("reason", ("withdrawn_before_enrollment", "withdrawn_citing_other_trial")),
        name="reason",
    ),
)

quote_checks = Table(
    "quote_checks",
    metadata,
    # One row per quote checked (accepted or not). Local only: claimed quotes and spans are source
    # text and never leave the machine.
    Column("check_id", String, primary_key=True),
    Column("run_id", String, nullable=False),
    Column("source_id", String, ForeignKey("sources.source_id"), nullable=False),
    Column("model_key", String, nullable=False),
    Column("role", String, nullable=False),  # extractor | tiebreak
    Column("statement_idx", Integer),
    Column("field", String),
    Column("statement", JSON),
    Column("claimed_quote", Text),
    Column("matched_span", Text),
    Column("score", Float, nullable=False),
    Column("method", String, nullable=False),  # exact | fuzzy | rejected
    Column("accepted", Boolean, nullable=False),
    Column("reject_reason", String),
    Column("threshold", Float, nullable=False),
    Column("matcher_version", String, nullable=False),
    Column("created_recorded_at", TS, nullable=False),
    CheckConstraint(_in("method", ("exact", "fuzzy", "rejected")), name="method"),
)
Index("ix_quote_checks_source", quote_checks.c.source_id)

# --------------------------------------------------------------------------- shared

completions = Table(
    "completions",
    metadata,
    Column("cache_key", String(64), primary_key=True),
    Column("provider", String, nullable=False),
    Column("model_version", String, nullable=False),
    Column("prompt_hash", String(64), nullable=False),
    Column("params", JSON, nullable=False),
    Column("sample_index", Integer, nullable=False),
    Column("response_path", Text, nullable=False),
    Column("tokens_in", Integer, nullable=False),
    Column("tokens_cached", Integer, nullable=False),
    Column("tokens_out", Integer, nullable=False),
    Column("tokens_reasoning", Integer, nullable=False),
    Column("cost_usd", Float, nullable=False),
    Column("batch_id", String),
    Column("run_id", String, nullable=False),
    Column("created_at", TS, nullable=False),
)

spend_ledger = Table(
    "spend_ledger",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("run_id", String, nullable=False),
    Column("job_kind", String, nullable=False),
    Column("approval", String, nullable=False),
    Column("est_usd", Float, nullable=False),
    Column("cap_usd", Float, nullable=False),
    Column("actual_usd", Float, nullable=False),
    Column("n_calls", Integer, nullable=False),
    Column("n_cached", Integer, nullable=False),
    Column("by_model", JSON, nullable=False),
    Column("status", String, nullable=False),  # running | finished | halted_at_cap | failed
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS),
)

model_snapshots = Table(
    "model_snapshots",
    metadata,
    Column("sha256", String(64), primary_key=True),
    Column("yaml", Text, nullable=False),
    Column("recorded_at", TS, nullable=False),
)

ingest_runs = Table(
    "ingest_runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("started_at", TS, nullable=False),
    Column("finished_at", TS),
    Column("stats", JSON),
)


# --------------------------------------------------------------------------- engine


def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


@cache
def get_engine() -> Engine:
    return make_engine(settings().db_url)


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)

"""Which event a statement attaches to. One drug in several diseases is several trials, and a second
statement from the same document is never silently dropped (found in pilot run 3: Evommune's
EVO756 readouts in CSU, AD and migraine collapsed into the CSU event)."""

from datetime import date

from sqlalchemy import func, select

from techbio.core.db import events, labels, promises
from techbio.ledger.apply import Provenance, Statement, apply_statement

from .conftest import add_source

D = date(2026, 5, 7)


def guidance(indication, start, end, **kw):
    return Statement(
        kind="guidance",
        event_type="readout",
        asset_name="EVO756",
        indication=indication,
        phase="2b",
        timing_text=f"{start}..{end}",
        window_start=date.fromisoformat(start),
        window_end=date.fromisoformat(end),
        window_precision="range",
        **kw,
    )


def prov(src, sponsor, d=D):
    return Provenance(src, sponsor, d, "auto-agreement:a+b", "auto-agreement")


def count(conn, table):
    return conn.execute(select(func.count()).select_from(table)).scalar_one()


def test_one_drug_in_three_diseases_is_three_events(engine, sponsor, tmp_path):
    add_source(engine, sponsor, "<p>x</p>", source_id="s1", tmp_path=tmp_path)
    with engine.begin() as c:
        ids = [
            apply_statement(c, guidance(ind, a, b), prov("s1", sponsor)).event_id
            for ind, a, b in (
                ("chronic spontaneous urticaria (CSU)", "2026-06-01", "2026-06-30"),
                ("moderate-to-severe AD patients", "2026-07-01", "2026-09-30"),
                ("migraine prophylaxis", "2027-01-01", "2027-12-31"),
            )
        ]
        assert len(set(ids)) == 3 and None not in ids
        assert (count(c, events), count(c, promises)) == (3, 3)


def test_a_restatement_in_other_words_finds_the_same_event(engine, sponsor, tmp_path):
    for s in ("s1", "s2", "s3"):
        add_source(engine, sponsor, "<p>x</p>", source_id=s, tmp_path=tmp_path)
    with engine.begin() as c:
        first = apply_statement(
            c,
            guidance("moderate-to-severe AD patients", "2026-07-01", "2026-09-30"),
            prov("s1", sponsor),
        ).event_id
        for s, ind in (("s2", "atopic dermatitis"), ("s3", "Dermatitis, Atopic")):
            r = apply_statement(c, guidance(ind, "2026-10-01", "2026-12-31"), prov(s, sponsor))
            assert r.event_id == first and not r.ambiguous
        assert count(c, promises) == 3  # the slip is recorded on the one event


def test_a_shared_trial_id_outweighs_the_wording(engine, sponsor, tmp_path):
    add_source(engine, sponsor, "<p>x</p>", source_id="s1", tmp_path=tmp_path)
    add_source(engine, sponsor, "<p>x</p>", source_id="s2", tmp_path=tmp_path)
    with engine.begin() as c:
        a = apply_statement(
            c,
            guidance("Urticaria", "2026-06-01", "2026-06-30", nct_id="NCT06000001"),
            prov("s1", sponsor),
        ).event_id
        b = apply_statement(
            c,
            guidance("CSU", "2026-07-01", "2026-07-31", nct_id="NCT06000001"),
            prov("s2", sponsor),
        ).event_id
        assert a == b


def test_an_unknown_or_generic_indication_still_matches(engine, sponsor, tmp_path):
    for s in ("s1", "s2", "s3"):
        add_source(engine, sponsor, "<p>x</p>", source_id=s, tmp_path=tmp_path)
    with engine.begin() as c:
        first = apply_statement(
            c,
            guidance("platinum-resistant ovarian cancer", "2026-01-01", "2026-12-31"),
            prov("s1", sponsor),
        ).event_id
        for s, ind in (("s2", None), ("s3", "advanced solid tumors")):
            assert (
                apply_statement(
                    c, guidance(ind, "2026-06-01", "2026-12-31"), prov(s, sponsor)
                ).event_id
                == first
            )


def test_a_conflicting_second_statement_from_one_document_is_queued_not_dropped(
    engine, sponsor, tmp_path
):
    add_source(engine, sponsor, "<p>x</p>", source_id="s1", tmp_path=tmp_path)
    with engine.begin() as c:
        first = apply_statement(c, guidance(None, "2026-06-01", "2026-06-30"), prov("s1", sponsor))
        again = apply_statement(c, guidance(None, "2026-06-01", "2026-06-30"), prov("s1", sponsor))
        assert again.event_id == first.event_id and not again.ambiguous  # a repeat is harmless
        other = apply_statement(c, guidance(None, "2027-01-01", "2027-12-31"), prov("s1", sponsor))
        assert other.event_id is None
        assert [x["event_id"] for x in other.ambiguous] == [first.event_id]
        assert "2026-06-01" in other.ambiguous[0]["conflict"]
        assert (count(c, events), count(c, promises)) == (1, 1)


def test_a_second_result_from_one_document_never_supersedes_the_first(engine, sponsor, tmp_path):
    add_source(engine, sponsor, "<p>x</p>", source_id="s1", tmp_path=tmp_path)
    out = dict(kind="outcome", event_type="readout", asset_name="EVO756", event_date=D, quote="x")
    with engine.begin() as c:
        met = apply_statement(c, Statement(result_category="met", **out), prov("s1", sponsor))
        missed = apply_statement(c, Statement(result_category="missed", **out), prov("s1", sponsor))
        assert missed.event_id is None and [x["event_id"] for x in missed.ambiguous] == [
            met.event_id
        ]
        values = c.execute(
            select(labels.c.value).where(labels.c.field == "result_category")
        ).scalars()
        assert list(values) == ["met"]

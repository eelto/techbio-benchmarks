"""When an outcome happened (critical piece 7; decisions 2026-11-05, Found 2, and run 7's fallback).

- A CT.gov stop is dated by the registry's actual primary completion date, not by the day the
  record was last edited (NCT05074420 ended 2024-09-05 and was stored as a 2026-08-11 stop).
- An outcome dated before the ledger's start (2025-01-01, the brief's fixed scope) never reaches
  the ledger; the drop stays on record.
- An outcome the extractors leave undated takes the date the document carries (its dateline)
  before the filing date (Sanofi's COAST 1: released 2026-03-28, filed on a 6-K 2026-03-31).
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from techbio.core.db import events, labels, resolutions, review_queue
from techbio.ledger.extract import dateline, run_extraction, run_prefilter
from techbio.ledger.review import decide, open_items
from techbio.ledger.scope import LEDGER_START

from .conftest import add_source
from .test_extract_pipeline import st
from .test_stop_rules import store, study

WHY = "The study was stopped for lack of efficacy at the planned interim analysis"
DATELINE_HTML = (
    "<html><body><p>Example Therapeutics Reports Phase 3 Results</p>"
    "<p>PARIS, March 28, 2026 -- Example Therapeutics announced that the Phase 3 HORIZON-2 trial"
    " of zorbalimab met its primary endpoint, with a statistically significant improvement in"
    " EASI-75 at week 16.</p></body></html>"
)
OUTCOME_Q = "the Phase 3 HORIZON-2 trial of zorbalimab met its primary endpoint"
FILED = datetime(2026, 3, 31, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("text", "filed", "expected"),
    [
        ("PARIS, March 28, 2026 -- Example announced", date(2026, 3, 31), date(2026, 3, 28)),
        ("BOSTON, Mass., Jan. 5, 2026 /PRNewswire/ --", date(2026, 1, 5), date(2026, 1, 5)),
        ("SAN DIEGO, Sept. 30, 2025 (GLOBE NEWSWIRE)", date(2025, 10, 2), date(2025, 9, 30)),
        ("Basel, 28 March 2026 - Example announced", date(2026, 3, 31), date(2026, 3, 28)),
        # A date after the filing cannot be the release date (a headline's upcoming meeting).
        ("Data to be presented on May 15, 2026", date(2026, 3, 31), None),
        # Nor can one more than two weeks before it.
        ("Webcast replay, March 2, 2026", date(2026, 3, 31), None),
        # Balance and period dates are not release dates, however close (pool, 2026-11-05).
        ("Cash of $2.2 billion as of March 27, 2026 -- BOSTON", date(2026, 3, 31), None),
        ("Results for the quarter ended March 27, 2026", date(2026, 3, 31), None),
        # An exhibit number or slide page before a month is not a day.
        ("Exhibit 99.2  March 2026 Corporate Presentation", date(2026, 3, 31), None),
        ("No date here at all", date(2026, 3, 31), None),
        # The first plausible date wins.
        (
            "Webcast on April 9, 2026. NEW YORK, March 30, 2026 -- March 1, 2026",
            date(2026, 3, 31),
            date(2026, 3, 30),
        ),
    ],
)
def test_dateline(text, filed, expected):
    assert dateline(text, filed) == expected


def stopped_answers(model_key, req):
    if "ClinicalTrials.gov record" not in req.user:
        return {"statements": []}
    return {
        "statements": [
            st(
                kind="outcome",
                asset_name="lasmiditan",
                asset_aliases=[],
                trial_name=None,
                nct_id=None,
                timing_text=None,
                result_category="stopped",
                result_subtype="futility",
                sponsor_explanation_category="efficacy",
                stop_data_trigger="interim_analysis",
                quote=WHY,
            )
        ]
    }


def ctgov_study(nct, completed):
    s = study(nct, "TERMINATED", 214, WHY)
    s["protocolSection"]["statusModule"]["primaryCompletionDateStruct"] = {
        "date": completed,
        "type": "ACTUAL",
    }
    return s


def test_a_registry_stop_is_dated_by_its_primary_completion_not_its_last_edit(
    engine, sponsor, fake, tmp_path
):
    fake(stopped_answers)
    store(engine, sponsor, tmp_path, ctgov_study("NCT06685835", "2025-06-11"))  # edited 2026-09-02
    run_prefilter(engine)
    out = run_extraction(engine, execute=True)
    assert out["accepted"] == 1
    with engine.connect() as c:
        r = c.execute(select(resolutions)).mappings().one()
        lab = c.execute(select(labels).where(labels.c.field == "event_date")).mappings().one()
    assert str(r["event_date"]) == "2025-06-11"
    assert lab["value"] == "2025-06-11" and lab["valid_at"].date() == date(2025, 6, 11)


def test_a_registry_stop_from_before_the_ledger_start_never_reaches_the_ledger(
    engine, sponsor, fake, tmp_path
):
    assert date(2025, 1, 1) == LEDGER_START
    fake(stopped_answers)
    store(engine, sponsor, tmp_path, ctgov_study("NCT05074420", "2024-09-05"))
    run_prefilter(engine)
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["queued"], out["out_of_scope"]) == (0, 0, 1)
    with engine.connect() as c:
        assert c.execute(select(events)).first() is None
        (item,) = c.execute(select(review_queue)).mappings().all()
    assert (item["status"], item["field"], item["closed_by"]) == (
        "closed",
        "event_date",
        "auto:scope",
    )
    assert item["payload"]["statement"]["event_date"] == "2024-09-05"


def test_a_dated_outcome_from_before_the_ledger_start_is_dropped(engine, sponsor, fake, tmp_path):
    def old(model_key, req):
        return {
            "statements": [
                st(
                    kind="outcome",
                    timing_text=None,
                    result_category="met",
                    event_date="2022-11-30",
                    quote=OUTCOME_Q,
                )
            ]
        }

    fake(old)
    add_source(engine, sponsor, DATELINE_HTML, published=FILED, tmp_path=tmp_path)
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["out_of_scope"]) == (0, 1)
    with engine.connect() as c:
        assert c.execute(select(events)).first() is None


def undated(cat_b="met"):
    def answers(model_key, req):
        cat = "met" if model_key == "extractor_a" else cat_b
        return {
            "statements": [
                st(kind="outcome", timing_text=None, result_category=cat, quote=OUTCOME_Q)
            ]
        }

    return answers


def test_an_undated_outcome_takes_the_documents_own_date_before_the_filing_date(
    engine, sponsor, fake, tmp_path
):
    fake(undated())
    add_source(engine, sponsor, DATELINE_HTML, published=FILED, tmp_path=tmp_path)
    assert run_extraction(engine, execute=True)["accepted"] == 1
    with engine.connect() as c:
        r = c.execute(select(resolutions)).mappings().one()
    assert str(r["event_date"]) == "2026-03-28"


def test_without_a_dateline_the_filing_date_still_applies(engine, sponsor, fake, tmp_path):
    fake(undated())
    html = DATELINE_HTML.replace("PARIS, March 28, 2026 -- ", "")
    add_source(engine, sponsor, html, published=FILED, tmp_path=tmp_path)
    run_extraction(engine, execute=True)
    with engine.connect() as c:
        r = c.execute(select(resolutions)).mappings().one()
    assert str(r["event_date"]) == "2026-03-31"


def test_the_operators_decision_uses_the_documents_own_date_too(engine, sponsor, fake, tmp_path):
    fake(undated(cat_b="mixed"))  # a reserved-field disagreement: the operator decides
    add_source(engine, sponsor, DATELINE_HTML, published=FILED, tmp_path=tmp_path)
    assert run_extraction(engine, execute=True)["queued"] == 1
    (item,) = open_items(engine)
    assert item["payload"]["document_date"] == "2026-03-28"
    decide(engine, item, "A", "operator")
    with engine.connect() as c:
        r = c.execute(select(resolutions)).mappings().one()
    assert str(r["event_date"]) == "2026-03-28" and r["result_category"] == "met"


def restated(sponsor, source, filed, dateline_date, event_date=None):
    from techbio.ledger.apply import Provenance, Statement

    st = Statement(
        kind="outcome",
        event_type="readout",
        asset_name="zorbalimab",
        trial_name="HORIZON-2",
        phase="3",
        result_category="met",
        event_date=event_date,
        quote=OUTCOME_Q,
    )
    return st, Provenance(
        source, sponsor, filed, "auto-agreement:a+b", "auto-agreement", None, dateline_date
    )


def event_date_now(c):
    from techbio.ledger.apply import current_labels

    (eid,) = c.execute(select(events.c.event_id)).scalars()
    return current_labels(c, eid)["event_date"][0], c.execute(
        select(resolutions.c.event_date)
    ).scalar_one()


def test_an_undated_restatement_never_moves_an_outcome_later(engine, sponsor, tmp_path):
    # A quarterly release restating a March result would otherwise re-date it to July (replay
    # 2026-11-05: Immutep's TACTI-004 stop, announced in March, dated by a July update).
    from techbio.ledger.apply import apply_statement

    add_source(engine, sponsor, DATELINE_HTML, published=FILED, tmp_path=tmp_path)
    add_source(engine, sponsor, DATELINE_HTML, source_id="src_2", tmp_path=tmp_path)
    with engine.begin() as c:
        apply_statement(c, *restated(sponsor, "src_1", date(2026, 3, 31), date(2026, 3, 28)))
        apply_statement(c, *restated(sponsor, "src_2", date(2026, 7, 14), date(2026, 7, 13)))
        label, resolved = event_date_now(c)
    assert label == "2026-03-28" and str(resolved) == "2026-03-28"


def test_an_older_report_read_later_moves_the_date_earlier(engine, sponsor, tmp_path):
    # The bootstrap reads newest first, so the original report often comes after a restatement.
    from techbio.ledger.apply import apply_statement

    add_source(engine, sponsor, DATELINE_HTML, published=FILED, tmp_path=tmp_path)
    add_source(engine, sponsor, DATELINE_HTML, source_id="src_2", tmp_path=tmp_path)
    with engine.begin() as c:
        apply_statement(c, *restated(sponsor, "src_2", date(2026, 7, 14), date(2026, 7, 13)))
        apply_statement(c, *restated(sponsor, "src_1", date(2026, 3, 31), date(2026, 3, 28)))
        label, resolved = event_date_now(c)
    assert label == "2026-03-28" and str(resolved) == "2026-03-28"


def test_a_date_the_document_states_always_applies(engine, sponsor, tmp_path):
    from techbio.ledger.apply import apply_statement

    add_source(engine, sponsor, DATELINE_HTML, published=FILED, tmp_path=tmp_path)
    add_source(engine, sponsor, DATELINE_HTML, source_id="src_2", tmp_path=tmp_path)
    with engine.begin() as c:
        apply_statement(c, *restated(sponsor, "src_1", date(2026, 3, 31), date(2026, 3, 28)))
        stated = date(2026, 4, 2)  # e.g. the topline came out after the release's preview
        apply_statement(c, *restated(sponsor, "src_2", date(2026, 7, 14), None, stated))
        label, _ = event_date_now(c)
    assert label == "2026-04-02"

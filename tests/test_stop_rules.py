"""Stop and exclusion rules in the ledger (operator decisions of 2026-10-30, second round).

- A strategic/business stop after enrollment is void unless a data trigger is documented, then it is
  scored as "missed"; either way it is recorded as `strategic_stop_after_enrollment` with the
  enrolled-patient count.
- A trial withdrawn before enrollment is not an event. One withdrawn citing another trial's data is
  not an event either, and is linked to that trial.
"""

from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from techbio.core.db import events, exclusions, labels, resolutions, review_queue, sources
from techbio.core.ids import sha256_json
from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.report import summary, write_exclusions
from techbio.ledger.review import decide, open_items
from techbio.ledger.sources import ctgov
from techbio.ledger.taxonomy import TAXONOMY_VERSION


def study(nct, status, enrolled, why, *, kind="ACTUAL", phases=("PHASE3",), drug="lasmiditan"):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": f"A study of {drug}"},
            "statusModule": {
                "overallStatus": status,
                "whyStopped": why,
                "lastUpdatePostDateStruct": {"date": "2026-09-02"},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Therapeutics, Inc."}},
            "designModule": {
                "phases": list(phases),
                "designInfo": {"allocation": "RANDOMIZED"},
                "enrollmentInfo": {"count": enrolled, "type": kind},
            },
            "armsInterventionsModule": {"interventions": [{"name": drug, "type": "DRUG"}]},
        }
    }


def store(engine, sponsor, tmp_path, s):
    fetcher = SimpleNamespace(raw_dir=tmp_path / "raw")
    t = ctgov.parse_study(s)
    ctgov._store_trial(engine, fetcher, sponsor, t, s)
    with engine.connect() as c:
        return c.execute(select(sources).where(sources.c.sha256 == sha256_json(s))).mappings().one()


def stop_statement(nct, trigger=None):
    return Statement(
        kind="outcome",
        event_type="readout",
        asset_name="lasmiditan",
        nct_id=nct,
        phase="3",
        result_category="stopped",
        result_subtype="business",
        sponsor_explanation_category="strategic_portfolio",
        stop_data_trigger=trigger,
        event_date=date(2026, 9, 2),
        quote="Study terminated due to strategic business decision",
    )


def test_business_stop_after_enrollment_is_void_and_logged_with_patient_count(
    engine, sponsor, tmp_path
):
    # NCT04396236: Lilly Phase 3, 847 enrolled, "strategic business decision".
    src = store(
        engine,
        sponsor,
        tmp_path,
        study(
            "NCT04396236", "TERMINATED", 847, "Study terminated due to strategic business decision"
        ),
    )
    assert src["meta"]["stopped"] is True  # an extraction input, not an exclusion
    prov = Provenance(src["source_id"], sponsor, date(2026, 9, 2), "human:operator", "human")
    with engine.begin() as c:
        res = apply_statement(c, stop_statement("NCT04396236"), prov)
        r = c.execute(select(resolutions)).mappings().one()
        ev = c.execute(select(events)).mappings().one()
        stated = c.execute(
            select(labels.c.value).where(labels.c.field == "sponsor_explanation_category")
        ).scalar_one()
    assert res.resolved
    assert (r["outcome_binary"], r["void_reason"]) == (None, "stopped_business")
    assert r["sponsor_explanation_category"] == "strategic_stop_after_enrollment"
    assert r["stated_explanation_category"] == stated == "strategic_portfolio"
    assert r["enrolled_at_stop"] == 847 and r["taxonomy_version"] == TAXONOMY_VERSION
    assert ev["status"] == "void"
    s = summary(engine)["strategic_stops_after_enrollment"]
    assert s == {"n": 1, "void": 1, "scored_missed": 0, "patients_enrolled": 847, "unknown_n": 0}


def test_business_stop_with_documented_interim_analysis_scores_as_missed(engine, sponsor, tmp_path):
    src = store(
        engine,
        sponsor,
        tmp_path,
        study("NCT04396236", "TERMINATED", 847, "Strategic decision following an interim analysis"),
    )
    prov = Provenance(src["source_id"], sponsor, date(2026, 9, 2), "human:operator", "human")
    with engine.begin() as c:
        apply_statement(c, stop_statement("NCT04396236", "interim_analysis"), prov)
        r = c.execute(select(resolutions)).mappings().one()
        ev = c.execute(select(events)).mappings().one()
    assert (r["outcome_binary"], r["void_reason"], r["scored_as"]) == (0, None, "missed")
    assert r["stop_data_trigger"] == "interim_analysis"
    assert r["sponsor_explanation_category"] == "strategic_stop_after_enrollment"
    assert ev["status"] == "resolved"


def test_withdrawn_before_enrollment_is_excluded_not_extracted(engine, sponsor, tmp_path):
    # NCT05951205: Vertex Phase 3, withdrawn, 0 enrolled.
    src = store(
        engine,
        sponsor,
        tmp_path,
        study("NCT05951205", "WITHDRAWN", 0, "Modification to the clinical development plan"),
    )
    assert src["meta"]["stopped"] is False and src["meta"]["excluded"] == (
        "withdrawn_before_enrollment"
    )
    with engine.connect() as c:
        ex = c.execute(select(exclusions)).mappings().one()
        assert c.execute(select(review_queue)).first() is None  # nothing to link
    assert (ex["nct_id"], ex["reason"], ex["enrolled"]) == (
        "NCT05951205",
        "withdrawn_before_enrollment",
        0,
    )
    # Re-ingesting a later version of the record does not duplicate the exclusion.
    store(
        engine,
        sponsor,
        tmp_path,
        study("NCT05951205", "WITHDRAWN", 0, "Modification to the clinical development plan."),
    )
    with engine.connect() as c:
        assert len(c.execute(select(exclusions)).all()) == 1


def test_withdrawn_citing_another_trial_is_linked_by_the_operator(engine, sponsor, tmp_path):
    # The cited trial: terminated after an interim analysis (NCT05592275, same asset, other code).
    store(
        engine,
        sponsor,
        tmp_path,
        study(
            "NCT05592275",
            "TERMINATED",
            332,
            "An interim was conducted ... low likelihood of study success",
            phases=("PHASE2",),
            drug="LY3540378",
        ),
    )
    # NCT06598631: withdrawn, cites "a related heart failure study" without its NCT number.
    store(
        engine,
        sponsor,
        tmp_path,
        study(
            "NCT06598631",
            "WITHDRAWN",
            0,
            "Study was terminated due to a lack of foreseeable clinical benefit, following the "
            "termination of a related heart failure study that demonstrated no benefit.",
            phases=("PHASE2",),
            drug="Volenrelaxin",
        ),
    )
    (item,) = open_items(engine)
    assert item["reason"] == "exclusion_link" and item["payload"]["nct_id"] == "NCT06598631"
    decide(engine, item, "link_trial", "operator", value="NCT05592275")
    with engine.connect() as c:
        ex = (
            c.execute(select(exclusions).where(exclusions.c.nct_id == "NCT06598631"))
            .mappings()
            .one()
        )
        assert c.execute(select(review_queue.c.status)).scalar_one() == "closed"
    assert ex["reason"] == "withdrawn_citing_other_trial"
    assert (ex["linked_nct_id"], ex["linked_by"]) == ("NCT05592275", "human:operator")


def test_cited_nct_number_links_without_the_queue(engine, sponsor, tmp_path):
    store(
        engine,
        sponsor,
        tmp_path,
        study("NCT09999999", "WITHDRAWN", 0, "Withdrawn based on the results of NCT01234567."),
    )
    with engine.connect() as c:
        ex = c.execute(select(exclusions)).mappings().one()
        assert c.execute(select(review_queue)).first() is None
    assert (ex["linked_nct_id"], ex["linked_by"]) == ("NCT01234567", "parser:ctgov_why_stopped_v1")


def test_open_event_for_an_excluded_trial_is_closed_as_excluded(engine, sponsor, tmp_path):
    src = store(
        engine,
        sponsor,
        tmp_path,
        study("NCT05951205", "RECRUITING", None, None),
    )
    guidance = Statement(
        kind="guidance",
        event_type="readout",
        asset_name="exa-cel",
        nct_id="NCT05951205",
        timing_text="2027",
        window_start=date(2027, 1, 1),
        window_end=date(2027, 12, 31),
        window_precision="year",
        quote="x",
    )
    prov = Provenance(
        src["source_id"], sponsor, date(2026, 3, 1), "auto-agreement:a+b", "auto-agreement"
    )
    with engine.begin() as c:
        eid = apply_statement(c, guidance, prov).event_id
    store(
        engine,
        sponsor,
        tmp_path,
        study("NCT05951205", "WITHDRAWN", 0, "Modification to the clinical development plan"),
    )
    with engine.connect() as c:
        ev = c.execute(select(events).where(events.c.event_id == eid)).mappings().one()
        lab = (
            c.execute(select(labels).where(labels.c.event_id == eid, labels.c.field == "excluded"))
            .mappings()
            .one()
        )
    assert ev["status"] == "excluded"
    assert lab["value"] == "withdrawn_before_enrollment" and lab["reviewer_kind"] == "deterministic"
    assert summary(engine)["exclusions"] == {"withdrawn_before_enrollment": 1}


def test_exclusions_export_has_reasons_and_links_but_no_registry_text(engine, sponsor, tmp_path):
    why = "Withdrawn based on the results of NCT01234567."
    store(engine, sponsor, tmp_path, study("NCT09999999", "WITHDRAWN", 0, why))
    out = tmp_path / "exclusions.csv"
    assert write_exclusions(engine, out) == 1
    body = out.read_text()
    assert "withdrawn_citing_other_trial" in body and "NCT01234567" in body
    assert "https://clinicaltrials.gov/study/NCT09999999" in body
    assert why[:20] not in body

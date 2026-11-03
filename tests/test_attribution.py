"""A readout is filed under the trial's lead sponsor on ClinicalTrials.gov, never under a partner that
mentions it (taxonomy §1, decision R.1). Found in the 2026-11-02 replay with Gemini as tie-breaker:
Zai Lab's release on argenx's ALKIVIA trial (no NCT number given) became a Zai Lab event. The
registry has ALKIVIA under argenx, and its title names efgartigimod (the intervention is listed only
as "EFG PH20 SC")."""

import pytest
from sqlalchemy import func, select

from techbio.core.db import events, now, review_queue, sponsors, trials
from techbio.ledger.extract import run_extraction
from techbio.ledger.review import queue_size
from techbio.ledger.scope import attribution, registry_trial

from .conftest import add_source
from .test_extract_pipeline import st
from .test_scope import trial

PARTNER = "spn_1"  # the fixture sponsor, Example Therapeutics: holds regional rights
LICENSOR = "spn_2"
ALKIVIA_LIKE = {
    "nct_id": "NCT07000002",
    "acronym": "SPARK",
    "phases": ["PHASE2", "PHASE3"],
    "lead_sponsor_name": "Licensor Bio",
    "brief_title": "A Study of EXT-404 PH20 SC in Adults With Active Myositis",
    "interventions": [{"name": "E404 PH20 SC", "type": "BIOLOGICAL"}, {"name": "PBO"}],
}
ASSETS = ["EXT-404", "exampligimod alfa"]


@pytest.fixture
def licensor(engine, sponsor):
    with engine.begin() as c:
        c.execute(
            sponsors.insert().values(
                sponsor_id=LICENSOR,
                name="Licensor Bio SE",
                cik=2,
                tickers=["LCNS"],
                exchange="Nasdaq",
                filer_kind="fpi",
                sic=2836,
                created_recorded_at=now(),
                updated_recorded_at=now(),
            )
        )
    return LICENSOR


def add_trial(engine, sponsor_id, **kw):
    with engine.begin() as c:
        c.execute(
            trials.insert().values(
                sponsor_id=sponsor_id,
                source_id="src_1",
                created_recorded_at=now(),
                updated_recorded_at=now(),
                **trial(**{**ALKIVIA_LIKE, **kw}),
            )
        )


@pytest.mark.parametrize(
    ("owner", "kw", "verdict"),
    [
        (LICENSOR, {}, "out"),  # the title names the asset
        (LICENSOR, {"brief_title": "A Study in Myositis"}, "in"),  # nothing ties it to the asset
        (PARTNER, {}, "in"),  # the sponsor's own trial
        (None, {}, "in"),  # no registry record: the extractors' reading stands
    ],
)
def test_attribution(owner, kw, verdict):
    t = trial(**{**ALKIVIA_LIKE, **kw}, sponsor_id=owner) if owner else None
    got, why = attribution(PARTNER, ASSETS, t)
    assert got == verdict
    assert ("R.1" in why) == (verdict == "out")


def test_an_acronym_finds_another_companys_trial_only_if_it_tests_the_asset(
    engine, licensor, tmp_path
):
    add_source(engine, PARTNER, DOC, tmp_path=tmp_path)
    add_trial(engine, LICENSOR)
    add_trial(engine, LICENSOR, nct_id="NCT07000003", acronym="SPARK+", brief_title="EXT-404 OLE")
    with engine.connect() as c:
        assert registry_trial(c, PARTNER, None, "spark", ASSETS)["nct_id"] == "NCT07000002"
        assert registry_trial(c, PARTNER, None, "SPARK", ["EXT-999"]) is None  # shared acronym
        assert registry_trial(c, PARTNER, None, "SPARK") is None  # no asset given


def test_the_sponsors_own_acronym_comes_first(engine, licensor, tmp_path):
    add_source(engine, PARTNER, DOC, tmp_path=tmp_path)
    add_trial(engine, LICENSOR)
    add_trial(engine, PARTNER, nct_id="NCT07000004", brief_title="A Study of EXT-404 in Gout")
    with engine.connect() as c:
        assert registry_trial(c, PARTNER, None, "SPARK", ASSETS)["nct_id"] == "NCT07000004"


Q = (
    "Topline results from the Phase 2/3 SPARK trial of EXT-404 in myositis, conducted by our "
    "partner Licensor Bio, are expected in the first half of 2027."
)
DOC = f"<html><body><p>{Q}</p></body></html>"


def spark(**kw):
    base = {
        "asset_name": "EXT-404",
        "asset_aliases": [],
        "trial_name": "SPARK",
        "indication": "myositis",
        "phase": "2/3",
        "quote": Q,
    }
    return st(**{**base, **kw})


def count_events(engine):
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(events)).scalar_one()


def test_a_partners_mention_of_its_licensors_trial_never_reaches_the_ledger_or_the_tiebreak(
    engine, licensor, fake, tmp_path
):
    def answers(model_key, req):
        assert model_key.startswith("extractor"), "no tie-break for another company's trial"
        timing = "first half of 2027" if model_key == "extractor_a" else "in 2027"
        return {"statements": [spark(timing_text=timing)]}

    fake(answers)
    add_source(engine, PARTNER, DOC, tmp_path=tmp_path)
    add_trial(engine, LICENSOR)
    out = run_extraction(engine, execute=True)
    assert (out["out_of_scope"], out["tiebreaks"], out["accepted"]) == (1, 0, 0)
    assert queue_size(engine)["total"] == 0 and count_events(engine) == 0
    with engine.connect() as c:
        item = c.execute(select(review_queue)).mappings().one()
    # The drop is on record, closed, with the registry facts that decided it.
    assert (item["reason"], item["field"], item["status"], item["closed_by"]) == (
        "scope_check",
        "sponsor_id",
        "closed",
        "auto:registry",
    )
    assert "R.1" in item["payload"]["scope"]
    reg = item["payload"]["registry"]
    assert (reg["nct_id"], reg["lead_sponsor_name"]) == ("NCT07000002", "Licensor Bio")


def test_a_partner_drop_applies_after_the_tiebreak_too(engine, licensor, fake, tmp_path):
    # Only one extractor names the trial, so the pair is not ruled out before routing; the merged
    # statement the tie-breaker settles still names it.
    def answers(model_key, req):
        if model_key == "tiebreak":
            return {"choices": [{"field": "phase", "choice": "A", "quote": Q}]}
        if model_key == "extractor_a":
            return {"statements": [spark()]}
        return {"statements": [spark(trial_name=None, phase="3")]}

    fake(answers)
    add_source(engine, PARTNER, DOC, tmp_path=tmp_path)
    add_trial(engine, LICENSOR)
    out = run_extraction(engine, execute=True)
    assert (out["tiebreaks"], out["out_of_scope"], out["accepted"]) == (1, 1, 0)
    assert count_events(engine) == 0


def test_another_companys_trial_with_the_same_acronym_does_not_drop_the_sponsors_readout(
    engine, licensor, fake, tmp_path
):
    fake(lambda model_key, req: {"statements": [spark()]})
    add_source(engine, PARTNER, DOC, tmp_path=tmp_path)
    add_trial(engine, LICENSOR, brief_title="A Study of LCN-7 in Myositis", interventions=[])
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["out_of_scope"]) == (1, 0)
    with engine.connect() as c:
        assert c.execute(select(events.c.sponsor_id)).scalar_one() == PARTNER


def test_a_wrong_nct_number_that_does_not_test_the_asset_does_not_drop_it(
    engine, licensor, fake, tmp_path
):
    fake(lambda model_key, req: {"statements": [spark(nct_id="NCT07000002")]})
    add_source(engine, PARTNER, DOC, tmp_path=tmp_path)
    add_trial(engine, LICENSOR, brief_title="A Study of LCN-7 in Myositis", interventions=[])
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["out_of_scope"]) == (1, 0)

"""A Phase 2 readout reaches the ledger only if it meets the 2b rule (taxonomy §1): randomized,
controlled, and called 2b, pivotal or registrational or N >= 100. The registry settles phase,
randomization and size; it can confirm a control arm but never rule one out, because sponsors often
label an active-comparator arm "experimental". Found in pilot run 3: DENALI (single drug, two doses)
and both tebapivat studies (not randomized; 59 patients) had been accepted."""

import pytest
from sqlalchemy import func, select

from techbio.core.db import events, now, review_queue, trials
from techbio.ledger.extract import run_extraction
from techbio.ledger.review import decide, open_items, queue_size
from techbio.ledger.scope import readout_scope

from .conftest import add_source
from .test_extract_pipeline import st


def trial(**kw):
    base = {
        "nct_id": "NCT07000001",
        "phases": ["PHASE2"],
        "allocation": "RANDOMIZED",
        "enrollment": 150,
        "brief_title": "A Study of EXT-404 in Sickle Cell Disease",
        "interventions": [{"name": "EXT-404", "type": "DRUG"}, {"name": "Placebo", "type": "DRUG"}],
    }
    base.update(kw)
    return base


ONE_DRUG = [{"name": "Azenosertib", "type": "DRUG"}]


@pytest.mark.parametrize(
    ("phase", "t", "verdict"),
    [
        ("2", trial(), "in"),  # placebo-controlled, N >= 100
        ("2b", trial(enrollment=59), "in"),  # small, but the sponsor calls it 2b
        ("2", trial(enrollment=59, brief_title="A Dose-Finding Study of Tebapivat"), "out"),
        ("2b", trial(allocation="NON_RANDOMIZED", enrollment=87), "out"),  # tebapivat, LR-MDS
        (None, trial(allocation="NA"), "out"),  # single arm
        ("2", trial(phases=["PHASE1", "PHASE2"]), "out"),
        ("2", trial(phases=["PHASE2", "PHASE3"], allocation="NA"), "in"),  # Phase 2/3
        ("2b", trial(enrollment=310, interventions=ONE_DRUG), "ask"),  # DENALI: two doses
        (
            "2",
            trial(
                enrollment=106,
                brief_title="A Study of MORAb-202 Versus Investigator's Choice Chemotherapy",
                interventions=[{"name": "MORAb-202"}, {"name": "Paclitaxel"}],
            ),
            "in",
        ),  # the chemotherapy arm is labelled "experimental" on CT.gov
        ("2", trial(allocation=None), "ask"),
        ("2", None, "ask"),  # no registry record: a plain Phase 2 needs a look
        ("2b", None, "in"),  # the extractors applied the rule from the document
        (None, None, "in"),
    ],
)
def test_readout_scope(phase, t, verdict):
    got, why = readout_scope(phase, t)
    assert got == verdict
    assert bool(why) == (verdict != "in")


DOC = (
    "<html><body><p>Topline results from the Phase 2 SPARK trial of EXT-404 in sickle cell "
    "disease are expected in the first half of 2027.</p></body></html>"
)
Q = (
    "Topline results from the Phase 2 SPARK trial of EXT-404 in sickle cell disease are expected "
    "in the first half of 2027."
)


def spark(**kw):
    base = {
        "asset_name": "EXT-404",
        "asset_aliases": [],
        "trial_name": "SPARK",
        "indication": "sickle cell disease",
        "phase": "2",
        "quote": Q,
    }
    return st(**{**base, **kw})


def add_trial(engine, sponsor_id, source_id, **kw):
    t = trial(acronym="SPARK", **kw)
    with engine.begin() as c:
        c.execute(
            trials.insert().values(
                sponsor_id=sponsor_id,
                source_id=source_id,
                created_recorded_at=now(),
                updated_recorded_at=now(),
                **t,
            )
        )


def count_events(engine):
    with engine.connect() as c:
        return c.execute(select(func.count()).select_from(events)).scalar_one()


def test_a_plain_phase_2_with_no_registry_record_goes_to_the_operator(
    engine, sponsor, fake, tmp_path
):
    fake(lambda model_key, req: {"statements": [spark()]})
    add_source(engine, sponsor, DOC, tmp_path=tmp_path)
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["queued"]) == (0, 1)
    assert queue_size(engine)["scope_check"] == 1 and count_events(engine) == 0

    (item,) = open_items(engine)
    eid = decide(engine, item, "keep", "operator")
    with engine.connect() as c:
        ev = c.execute(select(events).where(events.c.event_id == eid)).mappings().one()
    assert ev["phase"] == "2b"  # the operator ruled that it counts as 2b
    assert queue_size(engine)["total"] == 0


def test_a_readout_the_registry_rules_out_never_reaches_the_ledger_or_the_tiebreak(
    engine, sponsor, fake, tmp_path
):
    def answers(model_key, req):
        assert model_key.startswith("extractor"), "no tie-break for an out-of-scope trial"
        timing = "first half of 2027" if model_key == "extractor_a" else "in 2027"
        return {"statements": [spark(phase="2b", timing_text=timing)]}

    fake(answers)
    add_source(engine, sponsor, DOC, tmp_path=tmp_path)
    add_trial(engine, sponsor, "src_1", allocation="NON_RANDOMIZED", enrollment=87)
    out = run_extraction(engine, execute=True)
    assert (out["out_of_scope"], out["tiebreaks"], out["accepted"]) == (1, 0, 0)
    assert queue_size(engine)["total"] == 0 and count_events(engine) == 0
    with engine.connect() as c:
        item = c.execute(select(review_queue)).mappings().one()
    # The drop is on record, closed, with the registry facts that decided it.
    assert (item["reason"], item["status"], item["closed_by"]) == (
        "scope_check",
        "closed",
        "auto:registry",
    )
    assert "not randomized" in item["payload"]["scope"]
    assert item["payload"]["registry"]["nct_id"] == "NCT07000001"


def test_one_candidates_wrong_trial_number_does_not_sink_the_other(engine, sponsor, fake, tmp_path):
    # Pilot run 3, Agios: one extractor gave the sickle cell statement the LR-MDS trial's number.
    # Different numbers are never paired, so each statement is judged against its own trial.
    def answers(model_key, req):
        if model_key == "tiebreak":
            return {"choices": [{"field": "exists", "choice": "A", "quote": Q}]}
        nct = "NCT07000009" if model_key == "extractor_a" else "NCT07000001"
        return {"statements": [spark(nct_id=nct)]}

    fake(answers)
    add_source(engine, sponsor, DOC, tmp_path=tmp_path)
    add_trial(engine, sponsor, "src_1", nct_id="NCT07000009", allocation="NON_RANDOMIZED")
    add_trial(engine, sponsor, "src_1")  # NCT07000001: randomized, placebo, 150 patients
    out = run_extraction(engine, execute=True)
    assert (out["out_of_scope"], out["tiebreaks"], out["accepted"]) == (1, 1, 1)
    with engine.connect() as c:
        assert c.execute(select(events.c.nct_id)).scalar_one() == "NCT07000001"


def test_a_registry_confirmed_trial_is_accepted_as_before(engine, sponsor, fake, tmp_path):
    fake(lambda model_key, req: {"statements": [spark()]})
    add_source(engine, sponsor, DOC, tmp_path=tmp_path)
    add_trial(engine, sponsor, "src_1")  # randomized, placebo, 150 patients
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["queued"], out["out_of_scope"]) == (1, 0, 0)
    assert count_events(engine) == 1

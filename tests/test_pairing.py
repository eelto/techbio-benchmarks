"""Pairing the two extractors' statements (extract.pair). Found in pilot run 3, case 5: Agios's
tebapivat release guides a sickle cell readout and an LR-MDS readout. One extractor gave the sickle
cell statement the LR-MDS trial's NCT number, and the first-match pairing joined it with the other
extractor's LR-MDS statement, so phase and timing of two different trials went to a tie-break.
Pairs now never join clearly different diseases, and the best match wins over the first."""

from datetime import date

from techbio.ledger.extract import Cand, collapse_duplicates, pair, run_extraction, to_statement
from techbio.ledger.quotes import QuoteMatch

from .conftest import add_source
from .test_extract_pipeline import st

OK = QuoteMatch(True, "exact", 1.0, None)
D = date(2026, 1, 8)
MDS_NCT, SCD_NCT = "NCT05490446", "NCT06924970"


def cand(model_key, idx, **kw):
    raw = st(**{"asset_name": "tebapivat", "asset_aliases": [], "trial_name": None, **kw})
    return Cand(model_key, idx, raw, to_statement(raw, D), raw["confidence"], OK)


def a(idx, **kw):
    return cand("extractor_a", idx, **kw)


def b(idx, **kw):
    return cand("extractor_b", idx, **kw)


def pairs(left, right):
    return [(x.idx if x else None, y.idx if y else None) for x, y in pair(left, right)]


def test_a_wrong_nct_number_does_not_pair_two_diseases():
    left = [
        a(0, indication="Sickle Cell Disease", nct_id=MDS_NCT, phase="2"),  # A's wrong NCT number
        a(1, indication="Lower-Risk Myelodysplastic Syndromes", nct_id=MDS_NCT, phase="2b"),
    ]
    right = [
        b(0, indication="Sickle Cell Disease", nct_id=SCD_NCT, phase="2"),
        b(1, indication="LR-MDS", nct_id=MDS_NCT, phase="2b"),
    ]
    assert pairs(left, right) == [(0, None), (1, 1), (None, 0)]


def test_the_best_match_wins_over_the_first():
    left = [a(0, trial_name=None, indication=None), a(1, trial_name="ZEN-1", indication=None)]
    right = [b(0, trial_name="ZEN 1", indication=None), b(1, trial_name=None, indication=None)]
    assert pairs(left, right) == [(0, 1), (1, 0)]


def test_one_drug_in_two_diseases_pairs_by_disease():
    left = [a(0, indication="atopic dermatitis (AD)", timing_text="third quarter of 2026")]
    right = [
        b(0, indication="moderate-to-severe CSU", timing_text="June 2026"),
        b(1, indication="moderate-to-severe AD patients", timing_text="the third quarter of 2026"),
    ]
    assert pairs(left, right) == [(0, 1), (None, 0)]


def test_a_vague_or_missing_indication_still_pairs():
    left = [a(0, indication="advanced solid tumors")]
    assert pairs(left, [b(0, indication="non-small cell lung cancer")]) == [(0, 0)]
    assert pairs(left, [b(0, indication=None)]) == [(0, 0)]


def test_a_models_repeats_of_one_event_collapse_into_one():
    # Pilot, Vor Bio: one extractor reported one myasthenia gravis readout three times (the text,
    # a pipeline table and a summary list), so two lone copies went to "does it exist" tie-breaks.
    mg = dict(indication="Myasthenia Gravis", timing_text="1H27", phase="3")
    reps = [
        b(0, **mg, nct_id="NCT05737160"),
        b(1, **mg),
        b(2, **{**mg, "indication": "generalized myasthenia gravis"}),
        b(3, **{**mg, "indication": "Sjögren's Disease", "timing_text": "1H26"}),
    ]
    kept = collapse_duplicates(reps)
    assert [c.idx for c in kept] == [0, 3]
    assert kept[0].st.nct_id == "NCT05737160"


def test_repeats_that_differ_in_a_compared_field_stay_apart():
    # Roivant: two batoclimab timings in one release; the operator sees the disagreement.
    ted = dict(asset_name="batoclimab", indication="thyroid eye disease (TED)", phase="3")
    reps = [
        a(0, **ted, timing_text="first half of calendar year 2026"),
        a(1, **ted, timing_text="before the end of calendar year 2025"),
    ]
    assert [c.idx for c in collapse_duplicates(reps)] == [0, 1]


Q_MG = "Topline data from the global Phase 3 trial in myasthenia gravis are expected in 1H27."
DOC_MG = (
    f"<html><body><p>{Q_MG}</p><p>Pipeline: telitacicept, Phase 3, topline 1H27.</p></body></html>"
)


def test_repeats_never_reach_the_tiebreak(engine, sponsor, fake, tmp_path):
    def answers(model_key, req):
        assert model_key.startswith("extractor"), "a repeat is not a dispute"
        mg = st(
            asset_name="telitacicept",
            asset_aliases=[],
            trial_name=None,
            indication="Myasthenia Gravis",
            timing_text="1H27",
            quote=Q_MG,
        )
        return {"statements": [mg] if model_key == "extractor_a" else [mg, mg, mg]}

    fake(answers)
    add_source(engine, sponsor, DOC_MG, tmp_path=tmp_path)
    out = run_extraction(engine, execute=True)
    assert (out["accepted"], out["tiebreaks"], out["queued"]) == (1, 0, 0)
    assert out["duplicates_collapsed"] == 2

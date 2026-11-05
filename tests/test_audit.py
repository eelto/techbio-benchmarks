"""The audit of agreed outcomes (decisions V.2 and V.3, operator 2026-11-05).

The pool is every event whose current result was accepted by two extractors agreeing; the sample
is fixed by a seed set in advance; 0 or 1 errors in 60 passes.
"""

from datetime import date

from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.audit import agreed_outcomes, draw, passes, settings


def outcome(asset: str, result: str = "met") -> Statement:
    return Statement(
        kind="outcome",
        event_type="readout",
        asset_name=asset,
        trial_name=f"{asset.upper()}-1",
        phase="3",
        result_category=result,
        event_date=date(2026, 3, 2),
        quote="The trial met its primary endpoint.",
    )


def prov(sponsor: str, kind: str, source: str = "src_1") -> Provenance:
    reviewer = {
        "auto-agreement": "auto-agreement:extractor_a+extractor_b",
        "model-adjudicated": "model-adjudicated:gemini-4-argon",
        "human": "human:operator",
    }[kind]
    return Provenance(source, sponsor, date(2026, 3, 2), reviewer, kind)


def test_the_pool_is_every_agreed_outcome_once(engine, sponsor, tmp_path):
    from .conftest import add_source

    add_source(engine, sponsor, "<p>x</p>", tmp_path=tmp_path)
    add_source(engine, sponsor, "<p>y</p>", source_id="src_2", tmp_path=tmp_path)
    with engine.begin() as c:
        agreed = apply_statement(c, outcome("alpha"), prov(sponsor, "auto-agreement")).event_id
        apply_statement(c, outcome("beta"), prov(sponsor, "human"))
        apply_statement(c, outcome("gamma"), prov(sponsor, "model-adjudicated"))
        # Accepted by agreement, then corrected by the operator: no longer an agreed outcome.
        apply_statement(c, outcome("delta"), prov(sponsor, "auto-agreement"))
        apply_statement(c, outcome("delta", "missed"), prov(sponsor, "human", "src_2"))
        # The same agreed result from a second document is one outcome, not two.
        apply_statement(c, outcome("alpha"), prov(sponsor, "auto-agreement", "src_2"))
        pool = agreed_outcomes(c)
    assert [p["event_id"] for p in pool] == [agreed]
    assert pool[0]["field"] == "result_category" and pool[0]["value"] == "met"


def test_the_draw_is_fixed_by_the_seed(engine, sponsor, tmp_path):
    from .conftest import add_source

    add_source(engine, sponsor, "<p>x</p>", tmp_path=tmp_path)
    with engine.begin() as c:
        for i in range(30):
            apply_statement(c, outcome(f"drug{i:02d}"), prov(sponsor, "auto-agreement"))
        first = [r["label_id"] for r in draw(c, 10, 1494543743)]
        again = [r["label_id"] for r in draw(c, 10, 1494543743)]
        other = [r["label_id"] for r in draw(c, 10, 7)]
        everything = draw(c, 60, 1494543743)
    assert first == again and len(set(first)) == 10
    assert other != first
    assert len(everything) == 30  # a pool smaller than n is audited whole


def test_the_pass_bar_set_in_advance():
    cfg = settings()
    assert (cfg["n"], cfg["pass_max_errors"]) == (60, 1)
    assert isinstance(cfg["seed"], int)
    assert [passes(e, cfg) for e in (0, 1, 2, 5)] == [True, True, False, False]

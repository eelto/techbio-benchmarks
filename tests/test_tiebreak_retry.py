"""A tie-break that failed or never ran is retried on the next run, not left to the operator.

The document is marked done before its tie-breaks go out, so a refused batch, a crash or the cap
leaves the dispute in the queue with a note (decisions C.8, C.9). That is a failure, not the model
declining: the next run asks again, at most three times. A model's own "neither" stays with the
operator.
"""

import pytest
from sqlalchemy import select

from techbio.core.db import promises, review_queue
from techbio.ledger.extract import run_extraction

from .conftest import add_source
from .test_extract_pipeline import FIX, SUMMIT_Q, answers


def setup(engine, sponsor, tmp_path):
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )


def refusing(f):
    submit = f.submit

    def refuse(items, model):
        if model["role"] == "tiebreak":
            raise ValueError("400 INVALID_ARGUMENT")
        return submit(items, model)

    return refuse, submit


def queue(engine):
    with engine.connect() as c:
        return c.execute(select(review_queue).order_by(review_queue.c.created_at)).mappings().all()


def tiebreak_calls(f):
    return sum(1 for m, _ in f.calls if m == "tiebreak")


def test_a_refused_tiebreak_is_retried_on_the_next_run(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    f.submit, accept = refusing(f)
    setup(engine, sponsor, tmp_path)
    run_extraction(engine, execute=True)
    (failed,) = queue(engine)
    assert failed["status"] == "open" and failed["payload"]["note"].startswith("tie-break failed")

    f.submit = accept  # the provider answers this time; there is no new document
    out = run_extraction(engine, execute=True)
    assert (out["documents"], out["tiebreaks"], out["tiebreak_retries"]) == (0, 1, 1)
    (item,) = queue(engine)
    assert (item["item_id"], item["status"], item["closed_by"]) == (
        failed["item_id"],
        "closed",
        "auto:retry",
    )
    with engine.connect() as c:
        kinds = {p["reviewer_kind"] for p in c.execute(select(promises)).mappings()}
    assert "model-adjudicated" in kinds  # SUMMIT's window, decided by the tie-breaker


def test_a_tiebreak_that_never_ran_after_a_crash_is_retried(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    accept = f.submit

    def crash(items, model):
        if model["role"] == "tiebreak":
            raise ConnectionError("connection reset")
        return accept(items, model)

    f.submit = crash
    setup(engine, sponsor, tmp_path)
    with pytest.raises(ConnectionError):
        run_extraction(engine, execute=True)
    assert queue(engine)[0]["payload"]["note"] == "tie-break not run: ConnectionError"

    f.submit = accept
    assert run_extraction(engine, execute=True)["tiebreak_retries"] == 1
    assert [i["status"] for i in queue(engine)] == ["closed"]


def test_a_models_own_neither_stays_with_the_operator(engine, sponsor, fake, tmp_path):
    def neither(model_key, req):
        if model_key == "tiebreak":
            return {"choices": [{"field": "window", "choice": "neither", "quote": SUMMIT_Q}]}
        return answers(model_key, req)

    f = fake(neither)
    setup(engine, sponsor, tmp_path)
    run_extraction(engine, execute=True)
    n = tiebreak_calls(f)
    out = run_extraction(engine, execute=True)
    assert out == {"prefilter": out["prefilter"], "documents": 0}  # nothing to do
    assert tiebreak_calls(f) == n
    (item,) = queue(engine)
    assert item["status"] == "open" and "note" not in item["payload"]


def test_retries_stop_after_three_tries(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    f.submit, _ = refusing(f)
    setup(engine, sponsor, tmp_path)
    for _ in range(4):
        run_extraction(engine, execute=True)
    items = queue(engine)
    open_ = [i for i in items if i["status"] == "open"]
    assert len(items) == 3 and len(open_) == 1  # one dispute, never duplicated
    assert open_[0]["payload"]["attempts"] == 3
    assert [i["closed_by"] for i in items if i["status"] == "closed"] == ["auto:retry"] * 2


def test_the_dry_run_counts_the_retries(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    f.submit, _ = refusing(f)
    setup(engine, sponsor, tmp_path)
    run_extraction(engine, execute=True)
    n = len(f.calls)
    out = run_extraction(engine, execute=False)
    assert out["dry_run"] and out["documents"] == 0 and out["est_usd"] > 0
    assert len(f.calls) == n

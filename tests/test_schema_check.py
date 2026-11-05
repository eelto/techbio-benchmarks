"""Every answer is checked against the schema it was asked for, before it is cached.

Pilot re-measure, 2026-11-03: Google's batch service dropped the tie-break schema. Six answers in
shapes of the model's own choosing were cached as good answers, then read as abstentions, and all
six went to the operator's queue. A provider's promise to follow the schema is checked here."""

import pytest
from sqlalchemy import select

from techbio.core.db import review_queue
from techbio.core.llm import runner
from techbio.core.llm.cache import CompletionCache, LLMRequest
from techbio.core.spend import SpendGuard
from techbio.ledger.extract import TB_SCHEMA, run_extraction

from .conftest import add_source
from .test_extract_pipeline import FIX, answers

QUOTE = "Topline data were positive."


def tb_req() -> LLMRequest:
    return LLMRequest(
        "tiebreak", "You are the tie-breaker.", "Candidate A: ...", TB_SCHEMA, "tiebreak", 6000
    )


def guard(engine) -> SpendGuard:
    g = SpendGuard(engine, "ledger_extract", "run-1", execute=True, approval="test")
    g.authorize(runner.estimate("ledger_extract", {}, None, {}))
    return g


@pytest.mark.parametrize(
    "body",
    [
        {"decisions": ["A"], "quote": QUOTE},  # the pilot's shape: keys of its own
        {"choices": [{"field": "exists", "choice": QUOTE, "quote": "x"}]},  # outside the enum
        # A field the schema does not allow. Google's batch schema cannot say so (2026-11-04), so
        # this check is where `additionalProperties` is enforced for Gemini.
        {"choices": [{"field": "exists", "choice": "A", "quote": "x"}], "notes": QUOTE},
    ],
)
def test_an_answer_off_the_schema_is_an_error_and_never_cached(engine, fake, body):
    fake(lambda model_key, req: body)
    g = guard(engine)
    (resp,) = runner.run(engine, g, "tiebreak", [tb_req()], "run-1").values()
    assert not resp.ok and resp.error.startswith("answer does not follow the schema")
    assert QUOTE not in resp.error  # an error message never carries document text
    assert CompletionCache(engine).get(resp.cache_key) is None  # asked again next run
    assert g.actual_usd > 0  # it was still paid for, and the spend is recorded


def test_an_answer_on_the_schema_is_cached(engine, fake):
    fake(lambda model_key, req: {"choices": [{"field": "exists", "choice": "A", "quote": QUOTE}]})
    (resp,) = runner.run(engine, guard(engine), "tiebreak", [tb_req()], "run-1").values()
    assert resp.ok and CompletionCache(engine).get(resp.cache_key) is not None


def test_a_failed_tiebreak_is_queued_as_a_failure_not_an_abstention(
    engine, sponsor, fake, tmp_path
):
    def tiebreak_off_schema(model_key, req):
        if model_key == "tiebreak":
            return {"decisions": ["A"]}
        return answers(model_key, req)

    fake(tiebreak_off_schema)
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )
    out = run_extraction(engine, execute=True)
    assert out["errors"]["tiebreak"]["n"] == 1
    with engine.connect() as c:
        (item,) = c.execute(select(review_queue)).mappings()
    assert item["reason"] == "tiebreak_abstained"
    assert item["payload"]["note"].startswith("tie-break failed: answer does not follow the schema")

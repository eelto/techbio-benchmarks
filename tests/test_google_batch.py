"""The Gemini batch path (Q-G2): the tie-breaker runs at Google's batch price, half the interactive
one. No network: the client is a stand-in that returns SDK objects built from synthetic responses
shaped like the recorded pilot responses (2026-11-01).

Pilot re-measure, 2026-11-03: the batch service ignored the schema sent as `response_json_schema`.
All six tie-break answers came back as JSON in shapes of the model's own choosing, so none could be
read and all six went to the operator's queue as abstentions. Google's batch documentation sends
the schema as `response_schema`, and the batch path now does too.

Tie-break redo, 2026-11-04: Google refused that batch at submission, before any work or charge,
because its `response_schema` has no `additionalProperties`. The batch path leaves that keyword out;
the schema check (`runner.schema_error`) still enforces it on every answer. A refused batch is an
error for each of its requests: nothing is spent or cached, and no request is lost."""

import copy
import json
from types import SimpleNamespace

import pytest
from google.genai import errors, types

from techbio.core.config import model_cfg
from techbio.core.llm import providers, runner
from techbio.core.llm.cache import CompletionCache, LLMRequest, cache_key, request_params
from techbio.core.llm.providers import GoogleBatch, GoogleSync, google_config, provider_for
from techbio.core.spend import SpendGuard
from techbio.ledger.extract import SCHEMA, TB_SCHEMA

# The fields of a Gemini API `Schema` (Google's API reference), in the SDK's spelling. The refused
# batch of 2026-11-04 named only `additional_properties` as unknown.
GEMINI_SCHEMA_FIELDS = {
    "type", "format", "title", "description", "nullable", "enum", "max_items", "min_items",
    "properties", "required", "min_properties", "max_properties", "min_length", "max_length",
    "pattern", "example", "any_of", "property_ordering", "default", "items", "minimum", "maximum",
}  # fmt: skip

MODEL = {
    "provider": "google",
    "model_version": "gemini-4-argon",
    "price": {"input": 4.00, "cached_input": 0.20, "output": 20.00},
    "batch_discount": 0.5,
    "reasoning": {"thinking_level": "MEDIUM"},
}


def req(user: str = "Candidate A: ...", schema: dict | None = None) -> LLMRequest:
    return LLMRequest(
        "tiebreak", "You are the tie-breaker.", user, schema or {"type": "object"}, "tiebreak", 6000
    )


def answer(text: str, prompt: int = 5928, out: int = 72, thoughts: int = 0) -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}], "role": "model"}, "finish_reason": "STOP"}
        ],
        "model_version": "gemini-4-argon",
        "usage_metadata": {
            "prompt_token_count": prompt,
            "candidates_token_count": out,
            "thoughts_token_count": thoughts,
            "total_token_count": prompt + out + thoughts,
        },
    }


def job(state: str, responses: list[dict] | None = None) -> types.BatchJob:
    body: dict = {"name": "batches/abc123", "state": state}
    if responses is not None:
        body["dest"] = {"inlined_responses": responses}
    return types.BatchJob.model_validate(body)


class FakeBatches:
    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.created = []

    def create(self, *, model, src, config=None):
        self.created.append((model, src))
        return job("JOB_STATE_PENDING")

    def get(self, *, name):
        return self.jobs.pop(0)


def batch_provider(jobs=()) -> GoogleBatch:
    p = GoogleBatch.__new__(GoogleBatch)
    p.client = SimpleNamespace(batches=FakeBatches(jobs))
    return p


def test_each_batch_request_sends_the_schema_as_response_schema():
    p = batch_provider()
    one = req("one", TB_SCHEMA)
    assert p.submit([("k1", one), ("k2", req("two"))], MODEL) == "batches/abc123"
    ((model, src),) = p.client.batches.created
    assert model == "gemini-4-argon"
    assert [r.metadata for r in src] == [{"key": "k1"}, {"key": "k2"}]
    assert [r.contents for r in src] == ["one", "two"]
    cfg, sync = src[0].config, google_config(one, MODEL)
    assert cfg.response_json_schema is None and cfg.response_schema is not None
    assert cfg.response_mime_type == "application/json"
    # The synchronous path keeps `response_json_schema`, which it honored in pilot run 3.
    assert sync.response_json_schema == TB_SCHEMA and sync.response_schema is None
    # Everything else is the synchronous request.
    for f in ("system_instruction", "max_output_tokens", "thinking_config"):
        assert getattr(cfg, f) == getattr(sync, f)
    assert cfg.thinking_config.thinking_level == "MEDIUM" and cfg.max_output_tokens == 6000


def schema_fields(schema: dict) -> set[str]:
    """Every keyword used anywhere in a schema; property names are not keywords."""
    found = set(schema)
    for name in schema.get("properties", {}).values():
        found |= schema_fields(name)
    for sub in ([schema["items"]] if "items" in schema else []) + schema.get("any_of", []):
        found |= schema_fields(sub)
    return found


def test_the_request_google_receives_uses_only_fields_its_schema_has(monkeypatch):
    # The body the SDK would post, captured before it leaves the machine.
    monkeypatch.setenv("GOOGLE_API_KEY", "test-not-a-key")
    p = GoogleBatch()
    sent = []

    def post(method, path, body, http_options=None):
        sent.append(body)
        return SimpleNamespace(body=json.dumps({"name": "batches/abc123"}), headers={})

    monkeypatch.setattr(p.client._api_client, "request", post)
    one = req("one", TB_SCHEMA)
    before, key = copy.deepcopy(TB_SCHEMA), cache_key(one, MODEL)
    assert p.submit([("k1", one)], MODEL) == "batches/abc123"
    # The SDK edits the schema it is handed (it adds `property_ordering`). It gets a copy: the
    # request's schema is part of its cache key, and TB_SCHEMA is shared by every tie-break.
    assert before == TB_SCHEMA and cache_key(one, MODEL) == key
    ((item,),) = [b["batch"]["inputConfig"]["requests"]["requests"] for b in sent]
    config = item["request"]["generationConfig"]
    assert "responseJsonSchema" not in config and config["responseMimeType"] == "application/json"
    schema = config["responseSchema"]
    assert schema_fields(schema) <= GEMINI_SCHEMA_FIELDS
    # Every constraint Google can express is still sent.
    assert schema["required"] == ["choices"]
    choice = schema["properties"]["choices"]["items"]
    assert choice["required"] == ["field", "choice", "quote"]
    assert choice["properties"]["choice"]["enum"] == ["A", "B", "neither"]


def test_a_schema_the_batch_path_cannot_express_is_refused_before_submission():
    # The extraction schema uses type lists ("string" or null), which `response_schema` lacks.
    p = batch_provider()
    with pytest.raises(ValueError, match="response_schema"):
        p.submit([("k1", req("one", TB_SCHEMA)), ("k2", req("two", SCHEMA))], MODEL)
    assert p.client.batches.created == []


def test_a_batch_google_refuses_is_reported_as_refused():
    # A 4xx means the batch was not created, so nothing is charged. A 5xx or a lost connection
    # may have created it, and is not reported as a refusal.
    p = batch_provider()

    def create(**kw):
        raise errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT"}})

    p.client.batches.create = create
    with pytest.raises(ValueError, match="Google refused the batch: 400 INVALID_ARGUMENT"):
        p.submit([("k1", req("one", TB_SCHEMA))], MODEL)

    def create_5xx(**kw):
        raise errors.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})

    p.client.batches.create = create_5xx
    with pytest.raises(errors.ServerError):
        p.submit([("k1", req("one", TB_SCHEMA))], MODEL)


def test_an_oversized_batch_is_refused_before_submission():
    p = batch_provider()
    big = req("x" * (GoogleBatch.MAX_INLINE_BYTES + 1))
    with pytest.raises(ValueError, match="20 MB"):
        p.submit([("k1", big)], MODEL)
    assert p.client.batches.created == []


def test_collect_waits_then_maps_answers_by_key():
    done = job(
        "JOB_STATE_SUCCEEDED",
        [
            {"metadata": {"key": "k2"}, "response": answer('{"choices": []}', thoughts=40)},
            {"metadata": {"key": "k1"}, "error": {"code": 400, "message": "bad request"}},
        ],
    )
    p = batch_provider([job("JOB_STATE_RUNNING"), done])
    assert p.collect("batches/abc123", ["k1", "k2"]) is None
    out = {r.cache_key: r for r in p.collect("batches/abc123", ["k1", "k2"])}
    assert out["k2"].ok and out["k2"].text == '{"choices": []}'
    assert (out["k2"].tokens_in, out["k2"].tokens_out, out["k2"].tokens_reasoning) == (
        5928,
        112,
        40,
    )
    assert not out["k1"].ok and "bad request" in out["k1"].error


def test_answers_without_keys_follow_submission_order():
    done = job("JOB_STATE_SUCCEEDED", [{"response": answer("a")}, {"response": answer("b")}])
    out = batch_provider([done]).collect("batches/abc123", ["k1", "k2"])
    assert [(r.cache_key, r.text) for r in out] == [("k1", "a"), ("k2", "b")]


def test_answers_that_cannot_be_matched_are_errors_never_guesses():
    # One answer short and no keys: nothing can be attached to a request with confidence.
    done = job("JOB_STATE_SUCCEEDED", [{"response": answer("a")}])
    out = batch_provider([done]).collect("batches/abc123", ["k1", "k2"])
    assert {r.cache_key for r in out} == {"k1", "k2"} and not any(r.ok for r in out)
    # A key that was never sent is dropped, and the request it displaced is an error.
    stray = job("JOB_STATE_SUCCEEDED", [{"metadata": {"key": "zz"}, "response": answer("a")}])
    (r,) = batch_provider([stray]).collect("batches/abc123", ["k1"])
    assert (r.cache_key, r.ok, r.error) == ("k1", False, "no answer in the batch")


@pytest.mark.parametrize("state", ["JOB_STATE_FAILED", "JOB_STATE_EXPIRED", "JOB_STATE_CANCELLED"])
def test_a_job_that_ends_without_answers_errors_every_request(state):
    out = batch_provider([job(state)]).collect("batches/abc123", ["k1", "k2"])
    assert [r.cache_key for r in out] == ["k1", "k2"]
    assert all(not r.ok and state in r.error for r in out)


def test_the_tiebreaker_is_batched_at_half_price(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-not-a-key")
    tb = model_cfg("tiebreak")
    assert runner.is_batch(tb) and tb["batch_discount"] == 0.5
    assert isinstance(provider_for(tb), GoogleBatch)
    # A Google model with no batch discount configured stays synchronous.
    assert isinstance(provider_for({**tb, "batch_discount": 1.0}), GoogleSync)
    r = req()
    assert runner.worst_case_usd(r, tb) == pytest.approx(
        runner.worst_case_usd(r, {**tb, "batch_discount": 1.0}) / 2
    )


def test_a_google_batch_request_has_its_own_cache_key():
    # It sends the schema differently, so it is a different request. The six unreadable pilot
    # answers stay cached under the old key and are never reused.
    r = req("Candidate A: ...", TB_SCHEMA)
    sync = {**MODEL, "batch_discount": 1.0}
    assert cache_key(r, MODEL) != cache_key(r, sync)
    assert request_params(r, MODEL)["schema_field"] == "response_schema"
    # The synchronous key is unchanged (computed before this change), so pilot run 3's
    # synchronous answers are still found.
    assert "schema_field" not in request_params(r, sync)
    assert cache_key(r, sync) == "bb49a1c9cdd18b87df5e237f3007e499c72238489ab82b5f7501e8d5998f4405"
    # Anthropic and OpenAI send the same request either way, so batching never changes their key.
    for provider in ("anthropic", "openai"):
        m = {**MODEL, "provider": provider}
        assert cache_key(r, m) == cache_key(r, {**m, "batch_discount": 1.0})


def test_runner_sends_google_batches_in_smaller_chunks(engine, monkeypatch):
    from techbio.core.spend import SpendGuard

    p = batch_provider()
    sent = []

    def submit(items, model):
        sent.append(len(items))
        return f"b{len(sent)}"

    p.submit = submit
    p.collect = lambda batch_id, keys: [
        providers._google_response(k, types.GenerateContentResponse.model_validate(answer("{}")))
        for k in keys
    ]
    monkeypatch.setattr(runner, "_provider", lambda model: p)
    monkeypatch.setattr(GoogleBatch, "MAX_REQUESTS", 2)
    guard = SpendGuard(engine, "ledger_extract", "run-1", execute=True, approval="test")
    guard.authorize(runner.estimate("ledger_extract", {}, None, {}))
    reqs = [req(f"case {i}") for i in range(5)]
    out = runner.run(engine, guard, "tiebreak", reqs, "run-1")
    assert sent == [2, 2, 1] and len(out) == 5


def test_a_batch_the_provider_refuses_costs_nothing_and_loses_no_request(engine, monkeypatch):
    p = batch_provider()
    chunks = []

    def submit(items, model):
        chunks.append([k for k, _ in items])
        if len(chunks) == 1:
            raise ValueError("400 INVALID_ARGUMENT: Unknown name at generation_config")
        return "b2"

    p.submit = submit
    p.collect = lambda batch_id, keys: [
        providers._google_response(
            k, types.GenerateContentResponse.model_validate(answer('{"choices": []}'))
        )
        for k in keys
    ]
    monkeypatch.setattr(runner, "_provider", lambda model: p)
    monkeypatch.setattr(GoogleBatch, "MAX_REQUESTS", 2)
    guard = SpendGuard(engine, "ledger_extract", "run-1", execute=True, approval="test")
    guard.authorize(runner.estimate("ledger_extract", {}, None, {}))
    reqs = [req(f"case {i}", TB_SCHEMA) for i in range(3)]
    out = runner.run(engine, guard, "tiebreak", reqs, "run-1")
    refused, sent = chunks
    assert set(out) == set(refused) | set(sent) and len(out) == 3  # every request answered
    for k in refused:
        assert not out[k].ok and out[k].error.startswith("batch refused: 400 INVALID_ARGUMENT")
        assert out[k].cost_usd == 0 and CompletionCache(engine).get(k) is None
    assert all(out[k].ok for k in sent)  # the next chunk still goes out
    assert guard.reserved_usd == pytest.approx(0)  # the refused chunk's reservation is released
    assert guard.n_calls == 1 and guard.actual_usd == pytest.approx(out[sent[0]].cost_usd)
    assert runner._load_pending() == {}


def test_a_refused_tiebreak_batch_is_queued_as_a_failure_not_lost(engine, sponsor, fake, tmp_path):
    from sqlalchemy import select

    from techbio.core.db import review_queue, sources
    from techbio.ledger.extract import run_extraction

    from .conftest import add_source
    from .test_extract_pipeline import FIX, answers

    f = fake(answers)
    submit = f.submit

    def refuse_tiebreaks(items, model):
        if model["role"] == "tiebreak":
            raise ValueError("400 INVALID_ARGUMENT")
        return submit(items, model)

    f.submit = refuse_tiebreaks
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )
    out = run_extraction(engine, execute=True)  # the job finishes; it does not crash
    assert out["tiebreaks"] == 1 and out["errors"]["tiebreak"]["n"] == 1
    assert out["spend"]["by_model"].get("tiebreak", {}).get("usd", 0) == 0  # nothing charged
    with engine.connect() as c:
        (item,) = c.execute(select(review_queue)).mappings()
        (status,) = c.execute(select(sources.c.extract_status)).scalars()
    assert item["reason"] == "tiebreak_abstained" and status == "done"
    assert item["payload"]["note"] == "tie-break failed: batch refused: 400 INVALID_ARGUMENT"


def test_a_tiebreak_stage_that_crashes_queues_its_disputes_then_fails(
    engine, sponsor, fake, tmp_path
):
    # The document is already marked done when its tie-break goes out, so a crash there would drop
    # the disputed statement without trace (2026-11-04). It is queued first, then the job fails.
    from sqlalchemy import select

    from techbio.core.db import review_queue, spend_ledger
    from techbio.ledger.extract import run_extraction

    from .conftest import add_source
    from .test_extract_pipeline import FIX, answers

    f = fake(answers)
    submit = f.submit

    def lose_connection(items, model):
        if model["role"] == "tiebreak":
            raise ConnectionError("connection reset")
        return submit(items, model)

    f.submit = lose_connection
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )
    with pytest.raises(ConnectionError):
        run_extraction(engine, execute=True)
    with engine.connect() as c:
        (item,) = c.execute(select(review_queue)).mappings()
        (status,) = c.execute(select(spend_ledger.c.status)).scalars()
    assert item["reason"] == "tiebreak_abstained"
    assert item["payload"]["note"] == "tie-break not run: ConnectionError"
    assert status == "failed"

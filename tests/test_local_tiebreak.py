"""The local model (Ollama): the tie-breaker under P.1, the free pilot reference since P.3
(2026-11-02). Ollama's HTTP API is mocked: no
network, no model."""

import json
import re

import httpx
import pytest
import respx

from techbio.core.config import model_cfg
from techbio.core.llm import runner
from techbio.core.llm.cache import LLMRequest, cache_key
from techbio.core.llm.providers import OllamaSync
from techbio.ledger.extract import TB_SCHEMA

M = model_cfg("tiebreak_reference")
TAG, DIGEST = M["model_version"].split("@sha256:")
URL = M["endpoint"]


def req(max_out: int = 8000) -> LLMRequest:
    return LLMRequest(
        "tiebreak_reference", "system text", "user text", TB_SCHEMA, "tiebreak", max_out
    )


def tags(digest: str = DIGEST, name: str = TAG) -> dict:
    return {"models": [{"name": name, "model": name, "digest": digest}]}


def reply(content: str, done_reason: str = "stop") -> dict:
    return {
        "model": TAG,
        "message": {"role": "assistant", "content": content, "thinking": "A matches the text."},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": 2067,
        "eval_count": 246,
    }


def test_reference_is_local_pinned_free_and_thinking():
    assert M["provider"] == "ollama"
    # The exact weights: a tag alone can be re-pointed by a pull.
    assert re.fullmatch(r"[\w.\-]+:[\w.\-]+@sha256:[0-9a-f]{64}", M["model_version"])
    assert not any(M["price"].values())
    assert not runner.is_batch(M)
    # Thinking off returned "neither" or nothing on every probe (2026-10-31).
    assert M["reasoning"] == {"think": True}
    assert isinstance(M["seed"], int)
    # The tie-breaker is a third vendor, independent of both extractors (P.3).
    tb = model_cfg("tiebreak")
    assert tb["provider"] == "google" and not runner.is_batch(tb)
    assert tb["provider"] not in {model_cfg(k)["provider"] for k in ("extractor_a", "extractor_b")}


def test_weights_and_seed_are_in_the_cache_key():
    other = {**M, "model_version": f"{TAG}@sha256:{'0' * 64}"}
    assert cache_key(req(), M) != cache_key(req(), other)
    assert cache_key(req(), M) != cache_key(req(), {**M, "seed": M["seed"] + 1})


@respx.mock
def test_call_sends_schema_thinking_seed_and_output_cap():
    respx.get(f"{URL}/api/tags").respond(json=tags())
    route = respx.post(f"{URL}/api/chat").respond(json=reply('{"choices": []}'))
    r = OllamaSync(M).call("k1", req(), M)
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == TAG and body["stream"] is False and body["think"] is True
    assert body["format"] == TB_SCHEMA
    assert body["options"]["seed"] == M["seed"] and body["options"]["num_predict"] == 8000
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert r.ok and r.text == '{"choices": []}' and r.stop_reason == "stop"
    assert (r.tokens_in, r.tokens_out, r.cost_usd) == (2067, 246, 0.0)
    assert r.raw["message"]["thinking"]  # the thinking is kept with the completion, locally


@respx.mock
def test_hitting_the_output_cap_is_an_error_never_an_answer():
    respx.get(f"{URL}/api/tags").respond(json=tags())
    respx.post(f"{URL}/api/chat").respond(json=reply('{"choices": [{"fie', done_reason="length"))
    r = OllamaSync(M).call("k1", req(), M)
    assert not r.ok and r.error == "max_tokens"


@respx.mock
def test_a_failed_call_is_recorded_not_raised():
    respx.get(f"{URL}/api/tags").respond(json=tags())
    respx.post(f"{URL}/api/chat").mock(side_effect=httpx.ReadTimeout("slow"))
    r = OllamaSync(M).call("k1", req(), M)
    assert not r.ok and r.error.startswith("ReadTimeout")


@respx.mock
@pytest.mark.parametrize(
    ("served", "match"),
    [(tags(digest="0" * 64), "weights"), (tags(name="other:tag"), "not installed")],
)
def test_changed_or_missing_weights_are_refused(served, match):
    respx.get(f"{URL}/api/tags").respond(json=served)
    with pytest.raises(RuntimeError, match=match):
        OllamaSync(M)


@respx.mock
def test_server_down_is_refused_before_any_call():
    respx.get(f"{URL}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="not reachable"):
        OllamaSync(M)

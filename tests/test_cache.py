from techbio.core.config import model_cfg
from techbio.core.llm.cache import CompletionCache, LLMRequest, LLMResponse, cache_key


def req(i=0, user="u"):
    return LLMRequest("extractor_a", "sys", user, {"type": "object"}, "s", 1000, sample_index=i)


def test_cache_key_includes_sample_index_and_params():
    m = model_cfg("extractor_a")
    assert cache_key(req(0), m) != cache_key(req(1), m)
    assert cache_key(req(0), m) != cache_key(req(0, "other"), m)
    m2 = {**m, "reasoning": {"effort": "high"}}
    assert cache_key(req(0), m) != cache_key(req(0), m2)
    m3 = {**m, "model_version": "claude-haiku-5-6"}
    assert cache_key(req(0), m) != cache_key(req(0), m3)


def test_roundtrip_and_errors_not_cached(engine, tmp_path):
    cache = CompletionCache(engine, tmp_path / "c")
    m = model_cfg("extractor_a")
    r = req()
    k = cache_key(r, m)
    cache.put(r, m, LLMResponse(k, "", error="refusal"), "run")
    assert cache.get(k) is None
    cache.put(
        r,
        m,
        LLMResponse(k, '{"statements": []}', tokens_in=10, tokens_out=5, cost_usd=0.001),
        "run",
    )
    hit = cache.get(k)
    assert hit.from_cache and hit.parsed() == {"statements": []}

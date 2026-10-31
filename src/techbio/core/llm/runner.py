"""Run LLM requests through the cache and the spend guard.

Order of operations per model:
1. Cache hits are returned at $0.
2. Batches already submitted by an interrupted run are collected first, so nothing is paid twice.
3. Misses go out in chunks. Each chunk reserves its worst-case cost (estimated input + max output)
   with the guard before submission, so a job can never send a request that would cross its cap.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from rich.console import Console
from sqlalchemy import Engine

from techbio.core.config import model_cfg, settings
from techbio.core.llm.cache import CompletionCache, LLMRequest, LLMResponse, cache_key
from techbio.core.spend import CapExceeded, Estimate, LineItem, SpendGuard, price_tokens

console = Console(stderr=True)
CHUNK = 500
POLL_SECONDS = 30


def _pending_path() -> Path:
    return settings().cache_dir / "pending_batches.json"


def _load_pending() -> dict[str, Any]:
    p = _pending_path()
    return json.loads(p.read_text()) if p.exists() else {}


def _save_pending(d: dict[str, Any]) -> None:
    p = _pending_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1))


def is_batch(model: dict[str, Any]) -> bool:
    return model["provider"] in ("anthropic", "openai") and model.get("batch_discount", 1.0) < 1.0


def worst_case_usd(req: LLMRequest, model: dict[str, Any]) -> float:
    est_in = int(req.est_input_tokens(model.get("tokenizer_slack", 1.0)) * 1.2)
    return price_tokens(model, est_in, req.max_output_tokens, batch=is_batch(model))


def estimate(
    job_kind: str,
    requests_by_model: dict[str, list[LLMRequest]],
    cache: CompletionCache,
    expected_output_tokens: dict[str, int],
) -> Estimate:
    """Expected (not worst-case) cost; cache hits are free and shown separately."""
    est = Estimate(job_kind=job_kind)
    for model_key, reqs in requests_by_model.items():
        model = model_cfg(model_key)
        misses = [r for r in reqs if cache.get(cache_key(r, model)) is None]
        tin = sum(r.est_input_tokens(model.get("tokenizer_slack", 1.0)) for r in misses)
        tout = len(misses) * expected_output_tokens.get(model_key, 1500)
        est.items.append(
            LineItem(
                model_key=model_key,
                model_version=model["model_version"],
                n_calls=len(misses),
                n_cached=len(reqs) - len(misses),
                tokens_in=tin,
                tokens_out=tout,
                usd=round(price_tokens(model, tin, tout, batch=is_batch(model)), 4),
            )
        )
    return est


def run(
    engine: Engine,
    guard: SpendGuard,
    model_key: str,
    requests: Iterable[LLMRequest],
    run_id: str,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, LLMResponse]:
    """Return responses keyed by cache key. Requests the cap stopped are simply absent."""
    model = model_cfg(model_key)
    cache = CompletionCache(engine)
    batch = is_batch(model)
    say = on_progress or (lambda m: console.print(m))
    results: dict[str, LLMResponse] = {}
    todo: list[tuple[str, LLMRequest]] = []
    seen: set[str] = set()
    for req in requests:
        key = cache_key(req, model)
        if key in seen:
            continue
        seen.add(key)
        hit = cache.get(key)
        if hit is not None:
            results[key] = hit
            guard.record_cached(model_key)
        else:
            todo.append((key, req))

    by_key = dict(todo)

    def _settle(resp: LLMResponse, reserved: float) -> None:
        req = by_key[resp.cache_key]
        if resp.ok or resp.tokens_out:
            resp.cost_usd = price_tokens(
                model, resp.tokens_in, resp.tokens_out, resp.tokens_cached, batch=batch
            )
        guard.settle(model_key, reserved, resp.cost_usd, resp.tokens_in, resp.tokens_out)
        cache.put(req, model, resp, run_id)
        results[resp.cache_key] = resp

    if batch:
        provider = _provider(model)
        pending = _load_pending()
        # 2. collect batches left by an interrupted run for these exact requests
        for batch_id, meta in list(pending.items()):
            if meta["model_key"] != model_key or not set(meta["keys"]) & by_key.keys():
                continue
            say(f"collecting earlier batch {batch_id} ({len(meta['keys'])} requests)")
            reserved = meta["reserved_usd"]
            guard.reserved_usd += reserved
            out = _wait(provider, batch_id, say)
            per = reserved / max(len(out), 1)
            for resp in out:
                if resp.cache_key in by_key:
                    _settle(resp, per)
            pending.pop(batch_id)
            _save_pending(pending)
            todo = [(k, r) for k, r in todo if k not in results]
        # 3. submit the rest in chunks, reserving the worst case first
        for i in range(0, len(todo), CHUNK):
            chunk = todo[i : i + CHUNK]
            reserved = sum(worst_case_usd(r, model) for _, r in chunk)
            try:
                guard.reserve(reserved)
            except CapExceeded as e:
                say(f"[yellow]stopping before chunk {i // CHUNK + 1}: {e}[/]")
                break
            batch_id = provider.submit(chunk, model)
            pending[batch_id] = {
                "model_key": model_key,
                "run_id": run_id,
                "keys": [k for k, _ in chunk],
                "reserved_usd": reserved,
            }
            _save_pending(pending)
            say(f"submitted batch {batch_id}: {len(chunk)} requests to {model['model_version']}")
            out = _wait(provider, batch_id, say)
            per = reserved / max(len(out), 1)
            for resp in out:
                _settle(resp, per)
            guard.release(max(reserved - per * len(out), 0.0))
            pending.pop(batch_id)
            _save_pending(pending)
    else:
        provider = _provider(model)
        for key, req in todo:
            reserved = worst_case_usd(req, model)
            try:
                guard.reserve(reserved)
            except CapExceeded as e:
                say(f"[yellow]stopping: {e}[/]")
                break
            _settle(provider.call(key, req, model), reserved)
    return results


def _provider(model: dict[str, Any]):
    from techbio.core.llm.providers import provider_for

    return provider_for(model)


def _wait(provider, batch_id: str, say: Callable[[str], None]) -> list[LLMResponse]:
    waited = 0
    while True:
        out = provider.collect(batch_id)
        if out is not None:
            return out
        if waited % 300 == 0:
            say(f"  batch {batch_id} still processing ({waited // 60} min)")
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS

"""Thin provider adapters over each official SDK, plus a local Ollama model over its HTTP API.

Batch where the provider offers it on our path (Anthropic, OpenAI, and Google since 2026-11-03 for
models configured with a batch discount); synchronous otherwise (the local model has no batch
path). No sampling parameters are sent: current flagships
reject temperature, and the same rule applies to every vendor. The local model gets only a fixed
seed. Reasoning settings and seeds come from config/models.yaml and are recorded in the cache key.
"""

from __future__ import annotations

import io
import json
from typing import Any, Protocol

import httpx

from techbio.core.config import secret
from techbio.core.llm.cache import LLMRequest, LLMResponse


class BatchProvider(Protocol):
    def submit(self, items: list[tuple[str, LLMRequest]], model: dict[str, Any]) -> str: ...

    # `keys` are the batch's cache keys in submission order (for providers that echo none).
    def collect(self, batch_id: str, keys: list[str]) -> list[LLMResponse] | None: ...


class SyncProvider(Protocol):
    def call(self, key: str, req: LLMRequest, model: dict[str, Any]) -> LLMResponse: ...


# --------------------------------------------------------------------------- Anthropic


class AnthropicBatch:
    def __init__(self) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=secret("ANTHROPIC_API_KEY"))

    @staticmethod
    def params(req: LLMRequest, model: dict[str, Any]) -> dict[str, Any]:
        reasoning = model.get("reasoning", {})
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": req.json_schema},
        }
        if "effort" in reasoning:
            output_config["effort"] = reasoning["effort"]
        return {
            "model": model["model_version"],
            "max_tokens": req.max_output_tokens,
            # Shared instructions first, marked for caching across the batch.
            "system": [
                {"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": req.user}],
            "output_config": output_config,
        }

    def submit(self, items: list[tuple[str, LLMRequest]], model: dict[str, Any]) -> str:
        batch = self.client.messages.batches.create(
            requests=[{"custom_id": key, "params": self.params(req, model)} for key, req in items]
        )
        return batch.id

    def collect(self, batch_id: str, keys: list[str] | None = None) -> list[LLMResponse] | None:
        batch = self.client.messages.batches.retrieve(batch_id)
        if batch.processing_status != "ended":
            return None
        out: list[LLMResponse] = []
        for result in self.client.messages.batches.results(batch_id):
            key = result.custom_id
            if result.result.type != "succeeded":
                out.append(LLMResponse(cache_key=key, text="", error=result.result.type))
                continue
            msg = result.result.message
            text = next((b.text for b in msg.content if b.type == "text"), "")
            u = msg.usage
            cached = u.cache_read_input_tokens or 0
            created = u.cache_creation_input_tokens or 0
            thinking = (
                (u.output_tokens_details.thinking_tokens or 0) if u.output_tokens_details else 0
            )
            error = None
            if msg.stop_reason == "refusal":
                error = "refusal"
            elif msg.stop_reason == "max_tokens":
                error = "max_tokens"
            out.append(
                LLMResponse(
                    cache_key=key,
                    text=text,
                    tokens_in=u.input_tokens + cached + created,
                    tokens_cached=cached,
                    tokens_out=u.output_tokens,
                    tokens_reasoning=thinking,
                    stop_reason=msg.stop_reason,
                    error=error,
                    raw=msg.to_dict(),
                )
            )
        return out


# --------------------------------------------------------------------------- OpenAI


class OpenAIBatch:
    def __init__(self) -> None:
        import openai

        self.client = openai.OpenAI(api_key=secret("OPENAI_API_KEY"))

    @staticmethod
    def body(req: LLMRequest, model: dict[str, Any]) -> dict[str, Any]:
        reasoning = model.get("reasoning", {})
        body: dict[str, Any] = {
            "model": model["model_version"],
            "instructions": req.system,
            "input": req.user,
            "max_output_tokens": req.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": req.schema_name,
                    "schema": req.json_schema,
                    "strict": True,
                }
            },
            "store": False,
        }
        if "effort" in reasoning:
            body["reasoning"] = {"effort": reasoning["effort"]}
        return body

    def submit(self, items: list[tuple[str, LLMRequest]], model: dict[str, Any]) -> str:
        lines = [
            json.dumps(
                {
                    "custom_id": key,
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": self.body(req, model),
                }
            )
            for key, req in items
        ]
        f = self.client.files.create(
            file=("batch.jsonl", io.BytesIO("\n".join(lines).encode()), "application/jsonl"),
            purpose="batch",
        )
        batch = self.client.batches.create(
            input_file_id=f.id, endpoint="/v1/responses", completion_window="24h"
        )
        return batch.id

    def collect(self, batch_id: str, keys: list[str] | None = None) -> list[LLMResponse] | None:
        batch = self.client.batches.retrieve(batch_id)
        if batch.status not in ("completed", "failed", "expired", "cancelled"):
            return None
        out: list[LLMResponse] = []
        for file_id in (batch.output_file_id, batch.error_file_id):
            if not file_id:
                continue
            for line in self.client.files.content(file_id).text.splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                key = rec["custom_id"]
                resp = rec.get("response") or {}
                body = resp.get("body") or {}
                if rec.get("error") or resp.get("status_code") != 200:
                    out.append(
                        LLMResponse(
                            cache_key=key, text="", error=json.dumps(rec.get("error") or body)[:500]
                        )
                    )
                    continue
                text = ""
                for item in body.get("output", []):
                    if item.get("type") == "message":
                        for c in item.get("content", []):
                            if c.get("type") == "output_text":
                                text += c.get("text", "")
                u = body.get("usage", {})
                status = body.get("status")
                out.append(
                    LLMResponse(
                        cache_key=key,
                        text=text,
                        tokens_in=u.get("input_tokens", 0),
                        tokens_cached=(u.get("input_tokens_details") or {}).get("cached_tokens", 0),
                        tokens_out=u.get("output_tokens", 0),
                        tokens_reasoning=(u.get("output_tokens_details") or {}).get(
                            "reasoning_tokens", 0
                        ),
                        stop_reason=status,
                        error=None if status == "completed" else f"status:{status}",
                        raw=body,
                    )
                )
        return out


# --------------------------------------------------------------------------- Google


def batch_schema(schema: Any) -> Any:
    """The schema as the batch service's `response_schema` takes it: a fresh copy without
    `additionalProperties`, which that field lacks (Google refused the batch, 2026-11-04). The
    schema check (`runner.schema_error`) still enforces it on every answer. A copy, because the
    SDK edits the schema it is handed (it adds `property_ordering`), and a request's schema is part
    of its cache key."""
    if isinstance(schema, dict):
        return {
            k: batch_schema(v)
            for k, v in schema.items()
            if not (k == "additionalProperties" and isinstance(v, bool))
        }
    if isinstance(schema, list):
        return [batch_schema(v) for v in schema]
    return schema


def google_config(req: LLMRequest, model: dict[str, Any], batch: bool = False):
    """One request config for both paths, except the schema field. The batch service ignored
    `response_json_schema` (pilot re-measure, 2026-11-03: six tie-break answers in shapes of the
    model's own choosing), so batch requests send `response_schema`, as Google's batch docs do,
    in the form `batch_schema` gives. The synchronous path keeps `response_json_schema`, which it
    honored in pilot run 3. The cache key tells the two apart (`request_params`)."""
    from google.genai import types

    reasoning = model.get("reasoning", {})
    schema = (
        {"response_schema": batch_schema(req.json_schema)}
        if batch
        else {"response_json_schema": req.json_schema}
    )
    return types.GenerateContentConfig(
        system_instruction=req.system,
        response_mime_type="application/json",
        **schema,
        max_output_tokens=req.max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=reasoning["thinking_level"])
        if "thinking_level" in reasoning
        else None,
    )


def _google_response(key: str, r) -> LLMResponse:
    u = r.usage_metadata
    thoughts = (getattr(u, "thoughts_token_count", 0) or 0) if u else 0
    return LLMResponse(
        cache_key=key,
        text=r.text or "",
        tokens_in=(u.prompt_token_count or 0) if u else 0,
        tokens_cached=(getattr(u, "cached_content_token_count", 0) or 0) if u else 0,
        tokens_out=((u.candidates_token_count or 0) if u else 0) + thoughts,
        tokens_reasoning=thoughts,
        stop_reason=str(r.candidates[0].finish_reason) if r.candidates else None,
        error=None if r.text else "empty",
        raw=r.model_dump(mode="json", exclude_none=True),
    )


class GoogleSync:
    def __init__(self) -> None:
        from google import genai

        self.client = genai.Client(api_key=secret("GOOGLE_API_KEY"))

    def call(self, key: str, req: LLMRequest, model: dict[str, Any]) -> LLMResponse:
        try:
            r = self.client.models.generate_content(
                model=model["model_version"], contents=req.user, config=google_config(req, model)
            )
        except Exception as e:  # SDK raises typed errors; record and let the runner queue it
            return LLMResponse(cache_key=key, text="", error=f"{type(e).__name__}: {e}"[:500])
        return _google_response(key, r)


class GoogleBatch:
    """Gemini Batch API (Q-G2, 2026-11-03): half the interactive price, 24-hour target.

    Requests go inline, each tagged with its cache key in `metadata`. Google documents the key echo
    only for file input, and the SDK says inline answers come back in submission order, so an answer
    without a key takes its position, and anything that cannot be matched is an error, never a
    guess. Inline batches must stay under 20 MB; ours are about 30 KB per tie-break request.
    """

    MAX_REQUESTS = 300
    MAX_INLINE_BYTES = 18_000_000
    TERMINAL = (
        "JOB_STATE_SUCCEEDED",
        "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED",
        "JOB_STATE_EXPIRED",
    )

    def __init__(self) -> None:
        from google import genai

        self.client = genai.Client(api_key=secret("GOOGLE_API_KEY"))

    def submit(self, items: list[tuple[str, LLMRequest]], model: dict[str, Any]) -> str:
        """The batch's name. A ValueError means it was refused and not created, so nothing is
        charged: by our own checks, or by Google with a 4xx. Anything else (a 5xx, a lost
        connection) may have created it, and propagates."""
        from google.genai import errors, types

        size = sum(len((r.system + r.user + json.dumps(r.json_schema)).encode()) for _, r in items)
        if size > self.MAX_INLINE_BYTES:
            raise ValueError(f"Gemini inline batch of {size:,} bytes; the limit is 20 MB")
        src = []
        for key, req in items:
            try:
                config = google_config(req, model, batch=True)
            except (AttributeError, TypeError, ValueError) as e:
                # e.g. a type list ("string" or null), which `response_schema` cannot express
                raise ValueError(
                    f"schema {req.schema_name!r} cannot be sent as response_schema: {e}"
                ) from e
            src.append(
                types.InlinedRequest(contents=req.user, config=config, metadata={"key": key})
            )
        try:
            return self.client.batches.create(model=model["model_version"], src=src).name
        except errors.ClientError as e:
            raise ValueError(f"Google refused the batch: {e}") from e

    def collect(self, batch_id: str, keys: list[str]) -> list[LLMResponse] | None:
        job = self.client.batches.get(name=batch_id)
        state = job.state.value if job.state else None
        if state not in self.TERMINAL:
            return None
        answers = (job.dest.inlined_responses if job.dest else None) or []
        if state != "JOB_STATE_SUCCEEDED" or not answers:
            why = f"batch {state}: {job.error.message if job.error else 'no answers'}"[:500]
            return [LLMResponse(cache_key=k, text="", error=why) for k in keys]
        keyed = all((a.metadata or {}).get("key") for a in answers)
        if not keyed and len(answers) != len(keys):
            why = f"{len(answers)} unkeyed answers for {len(keys)} requests"
            return [LLMResponse(cache_key=k, text="", error=why) for k in keys]
        out: list[LLMResponse] = []
        for i, a in enumerate(answers):
            key = (a.metadata or {}).get("key") if keyed else keys[i]
            if key not in keys:
                continue
            if a.error or a.response is None:
                msg = a.error.message if a.error else "no response"
                out.append(LLMResponse(cache_key=key, text="", error=f"batch item: {msg}"[:500]))
                continue
            out.append(_google_response(key, a.response))
        answered = {r.cache_key for r in out}
        out += [
            LLMResponse(cache_key=k, text="", error="no answer in the batch")
            for k in keys
            if k not in answered
        ]
        return out


# --------------------------------------------------------------------------- Ollama (local)


class OllamaSync:
    """An open-weight model on the operator's machine: no spend, and nothing leaves the machine.

    `model_version` is `<tag>@sha256:<digest>`, the manifest digest Ollama reports. It is checked
    against the server before the first call, so a tag that was pulled again can never answer under
    the old version string (and its cached completions).
    """

    TIMEOUT_S = 900.0  # one call; the output cap bounds it at about 100 s on the Mac Studio

    def __init__(self, model: dict[str, Any]) -> None:
        self.url = model["endpoint"].rstrip("/")
        self.tag, _, digest = model["model_version"].partition("@sha256:")
        try:
            r = httpx.get(f"{self.url}/api/tags", timeout=10)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(
                f"Ollama is not reachable at {self.url} ({type(e).__name__}); start it first"
            ) from e
        served = {m["name"]: m["digest"] for m in r.json().get("models", [])}
        if self.tag not in served:
            raise RuntimeError(f"{self.tag} is not installed in the Ollama at {self.url}")
        if served[self.tag] != digest:
            raise RuntimeError(
                f"{self.tag} weights changed: the server has {served[self.tag][:12]}, "
                f"config/models.yaml pins {digest[:12]}"
            )

    def call(self, key: str, req: LLMRequest, model: dict[str, Any]) -> LLMResponse:
        body = {
            "model": self.tag,
            "stream": False,
            "think": model.get("reasoning", {}).get("think", False),
            "format": req.json_schema,
            "options": {
                "seed": model.get("seed"),
                "num_predict": req.max_output_tokens,
                "num_ctx": model.get("context_tokens", 32768),
            },
            "messages": [
                {"role": "system", "content": req.system},
                {"role": "user", "content": req.user},
            ],
        }
        try:
            r = httpx.post(f"{self.url}/api/chat", json=body, timeout=self.TIMEOUT_S)
            r.raise_for_status()
        except httpx.HTTPError as e:  # recorded; the runner leaves it uncached and the item queues
            return LLMResponse(cache_key=key, text="", error=f"{type(e).__name__}: {e}"[:500])
        data = r.json()
        text = (data.get("message") or {}).get("content") or ""
        done = data.get("done_reason")
        error = None
        if done == "length":
            error = "max_tokens"
        elif not text:
            error = "empty"
        return LLMResponse(
            cache_key=key,
            text=text,
            tokens_in=data.get("prompt_eval_count", 0),
            tokens_out=data.get("eval_count", 0),  # thinking included; Ollama doesn't split it
            stop_reason=done,
            error=error,
            raw=data,
        )


def provider_for(
    model: dict[str, Any],
) -> AnthropicBatch | OpenAIBatch | GoogleBatch | GoogleSync | OllamaSync:
    match model["provider"]:
        case "anthropic":
            return AnthropicBatch()
        case "openai":
            return OpenAIBatch()
        case "google":
            return GoogleBatch() if model.get("batch_discount", 1.0) < 1.0 else GoogleSync()
        case "ollama":
            return OllamaSync(model)
    raise NotImplementedError(f"provider {model['provider']!r} lands with the arena (Milestone 2)")

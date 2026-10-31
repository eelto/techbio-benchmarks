"""Thin provider adapters over each official SDK.

Batch where the provider offers it on our path (Anthropic, OpenAI); synchronous otherwise (Google
tie-breaks are few). No sampling parameters are sent: current flagships reject temperature, and the
same rule applies to every vendor. Reasoning settings come from config/models.yaml and are recorded
in the cache key.
"""

from __future__ import annotations

import io
import json
from typing import Any, Protocol

from techbio.core.config import secret
from techbio.core.llm.cache import LLMRequest, LLMResponse


class BatchProvider(Protocol):
    def submit(self, items: list[tuple[str, LLMRequest]], model: dict[str, Any]) -> str: ...

    def collect(self, batch_id: str) -> list[LLMResponse] | None: ...


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

    def collect(self, batch_id: str) -> list[LLMResponse] | None:
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

    def collect(self, batch_id: str) -> list[LLMResponse] | None:
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


class GoogleSync:
    def __init__(self) -> None:
        from google import genai

        self.client = genai.Client(api_key=secret("GOOGLE_API_KEY"))

    def call(self, key: str, req: LLMRequest, model: dict[str, Any]) -> LLMResponse:
        from google.genai import types

        reasoning = model.get("reasoning", {})
        config = types.GenerateContentConfig(
            system_instruction=req.system,
            response_mime_type="application/json",
            response_json_schema=req.json_schema,
            max_output_tokens=req.max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=reasoning["thinking_level"])
            if "thinking_level" in reasoning
            else None,
        )
        try:
            r = self.client.models.generate_content(
                model=model["model_version"], contents=req.user, config=config
            )
        except Exception as e:  # SDK raises typed errors; record and let the runner queue it
            return LLMResponse(cache_key=key, text="", error=f"{type(e).__name__}: {e}"[:500])
        u = r.usage_metadata
        thoughts = getattr(u, "thoughts_token_count", 0) or 0
        return LLMResponse(
            cache_key=key,
            text=r.text or "",
            tokens_in=u.prompt_token_count or 0,
            tokens_cached=getattr(u, "cached_content_token_count", 0) or 0,
            tokens_out=(u.candidates_token_count or 0) + thoughts,
            tokens_reasoning=thoughts,
            stop_reason=str(r.candidates[0].finish_reason) if r.candidates else None,
            error=None if r.text else "empty",
            raw=r.model_dump(mode="json", exclude_none=True),
        )


def provider_for(model: dict[str, Any]) -> AnthropicBatch | OpenAIBatch | GoogleSync:
    match model["provider"]:
        case "anthropic":
            return AnthropicBatch()
        case "openai":
            return OpenAIBatch()
        case "google":
            return GoogleSync()
    raise NotImplementedError(f"provider {model['provider']!r} lands with the arena (Milestone 2)")

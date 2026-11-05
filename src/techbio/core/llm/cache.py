"""Completion cache: every completion is stored, keyed so that re-runs are free.

cache_key = sha256(canonical_json({provider, model_version, prompt_hash, params, sample_index}))

`sample_index` is part of the key, so repeated samples (arena draws, harness repeats) are real draws
and never collapse onto one cached answer. `params` holds every setting that can change the output
(reasoning effort, max output tokens, schema hash, seed).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, insert, select

from techbio.core.config import settings
from techbio.core.db import completions
from techbio.core.ids import sha256_json


@dataclass
class LLMRequest:
    model_key: str
    system: str
    user: str
    json_schema: dict[str, Any]
    schema_name: str
    max_output_tokens: int
    sample_index: int = 0
    tag: str = ""  # caller's own reference (e.g. source_id); not part of the key

    def prompt_hash(self) -> str:
        return sha256_json({"system": self.system, "user": self.user})

    def est_input_tokens(self, slack: float = 1.0) -> int:
        # ~4 characters per token for English prose; the slack covers tokenizer differences.
        return int(
            (len(self.system) + len(self.user) + len(json.dumps(self.json_schema))) / 4 * slack
        )


@dataclass
class LLMResponse:
    cache_key: str
    text: str
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0  # includes reasoning tokens (billed as output by every provider)
    tokens_reasoning: int = 0
    cost_usd: float = 0.0
    stop_reason: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    def parsed(self) -> Any:
        return json.loads(self.text)


def is_batch(model: dict[str, Any]) -> bool:
    return (
        model["provider"] in ("anthropic", "openai", "google")
        and model.get("batch_discount", 1.0) < 1.0
    )


def request_params(req: LLMRequest, model: dict[str, Any]) -> dict[str, Any]:
    """Everything besides the prompt that can change the completion."""
    params = {
        "max_output_tokens": req.max_output_tokens,
        "reasoning": model.get("reasoning", {}),
        "schema_sha256": sha256_json(req.json_schema),
        "schema_name": req.schema_name,
        "seed": model.get("seed"),
    }
    if model["provider"] == "google" and is_batch(model):
        # Google's batch service ignored `response_json_schema` (pilot, 2026-11-03), so batch
        # requests send `response_schema`: a different request from the synchronous one.
        params["schema_field"] = "response_schema"
    return params


def cache_key(req: LLMRequest, model: dict[str, Any]) -> str:
    return sha256_json(
        {
            "provider": model["provider"],
            "model_version": model["model_version"],
            "prompt_hash": req.prompt_hash(),
            "params": request_params(req, model),
            "sample_index": req.sample_index,
        }
    )


class CompletionCache:
    def __init__(self, engine: Engine, root: Path | None = None) -> None:
        self.engine = engine
        self.root = root or (settings().cache_dir / "completions")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> LLMResponse | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(completions.c.response_path).where(completions.c.cache_key == key)
            ).first()
        if row is None:
            return None
        path = Path(row.response_path)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        data["from_cache"] = True
        return LLMResponse(**data)

    def put(
        self,
        req: LLMRequest,
        model: dict[str, Any],
        resp: LLMResponse,
        run_id: str,
        batch_id: str | None = None,
    ) -> None:
        if not resp.ok:
            return  # errors are never cached; the request is retried next run
        path = self._path(resp.cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = asdict(resp)
        record.pop("from_cache")
        path.write_text(json.dumps(record))
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(completions.c.cache_key).where(completions.c.cache_key == resp.cache_key)
            ).first()
            if exists:
                return
            conn.execute(
                insert(completions).values(
                    cache_key=resp.cache_key,
                    provider=model["provider"],
                    model_version=model["model_version"],
                    prompt_hash=req.prompt_hash(),
                    params=request_params(req, model),
                    sample_index=req.sample_index,
                    response_path=str(path),
                    tokens_in=resp.tokens_in,
                    tokens_cached=resp.tokens_cached,
                    tokens_out=resp.tokens_out,
                    tokens_reasoning=resp.tokens_reasoning,
                    cost_usd=resp.cost_usd,
                    batch_id=batch_id,
                    run_id=run_id,
                    created_at=datetime.now(UTC),
                )
            )

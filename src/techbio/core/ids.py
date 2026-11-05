"""Identifiers and hashing: ULID-based ids, run ids, canonical JSON, sha256."""

from __future__ import annotations

import hashlib
import json
import subprocess
import unicodedata
from typing import Any

from ulid import ULID

from techbio.core.timeutil import utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


def git_sha7() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or "nogit00"
    except (OSError, subprocess.CalledProcessError):
        return "nogit00"


def run_id(kind: str) -> str:
    """`<kind>-<YYYYMMDDTHHMMSSZ>-<git7>`"""
    return f"{kind}-{utcnow().strftime('%Y%m%dT%H%M%SZ')}-{git_sha7()}"


def _normalize(obj: Any) -> Any:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, float):
        # Fixed float format so hashes don't depend on repr quirks.
        return float(f"{obj:.10g}")
    if isinstance(obj, dict):
        return {_normalize(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_normalize(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    return json.dumps(
        _normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def sha256_json(obj: Any) -> str:
    return sha256_text(canonical_json(obj))

"""Config loading: YAML files under config/, secrets from .env (never from YAML)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def project_root() -> Path:
    env = os.environ.get("TECHBIO_ROOT")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for p in (here, *here.parents):
        if (p / "pyproject.toml").exists() and (p / "config").is_dir():
            return p
    # Fall back to the installed package location (src/techbio/core -> repo root).
    return Path(__file__).resolve().parents[3]


@cache
def load_yaml(name: str) -> dict[str, Any]:
    path = project_root() / "config" / f"{name}.yaml"
    with path.open() as f:
        return yaml.safe_load(f) or {}


@dataclass(frozen=True)
class Settings:
    root: Path
    data_dir: Path
    db_url: str

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


@cache
def settings() -> Settings:
    root = project_root()
    load_dotenv(root / ".env", override=False)
    data_dir = Path(os.environ.get("TECHBIO_DATA_DIR", root / "data"))
    if not data_dir.is_absolute():
        data_dir = root / data_dir
    db_url = os.environ.get("TECHBIO_DB_URL", f"sqlite:///{data_dir / 'ledger.sqlite'}")
    return Settings(root=root, data_dir=data_dir, db_url=db_url)


def secret(name: str, required: bool = True) -> str | None:
    """Read a secret from the environment (.env is loaded by settings()). Never logged."""
    settings()
    value = os.environ.get(name, "").strip()
    if required and not value:
        raise RuntimeError(f"{name} is not set. Add it to .env (see .env.example).")
    return value or None


def model_cfg(key: str) -> dict[str, Any]:
    models = load_yaml("models")["models"]
    if key not in models:
        raise KeyError(f"model key {key!r} not in config/models.yaml")
    return {"key": key, **models[key]}

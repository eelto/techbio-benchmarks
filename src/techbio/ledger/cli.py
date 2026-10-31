"""`ledger` CLI: ingest, extract (dry-run by default), review, report, sample."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from techbio.core.db import get_engine
from techbio.core.http import Fetcher

app = typer.Typer(no_args_is_help=True, help="Event ledger: catalysts, guidance, slips, outcomes.")
console = Console()


@app.command()
def ingest(
    source: Annotated[
        str, typer.Argument(help="universe | edgar | ctgov | fedreg | free (all of them)")
    ] = "free",
    lookback_days: Annotated[int | None, typer.Option(help="default: config/sources.yaml")] = None,
    limit: Annotated[
        int | None, typer.Option(help="only the first N sponsors (smoke runs)")
    ] = None,
) -> None:
    """Fetch from free public sources. No paid calls."""
    from techbio.ledger.sources import ctgov, edgar, fedreg

    engine = get_engine()
    with Fetcher() as f:
        if source in ("universe", "free"):
            console.print({"universe": edgar.build_universe(engine, f)})
        if source in ("edgar", "free"):
            console.print({"edgar": edgar.ingest(engine, f, lookback_days, limit)})
        if source in ("ctgov", "free"):
            console.print({"ctgov": ctgov.ingest(engine, f, lookback_days or 365, limit)})
        if source in ("fedreg", "free"):
            console.print({"fedreg": fedreg.ingest(engine, f, lookback_days or 365)})


@app.command()
def adcoms() -> None:
    """Apply parsed Federal Register AdCom notices to the ledger (deterministic, free)."""
    from techbio.ledger.adcom import apply_notices

    console.print(apply_notices(get_engine()))


@app.command()
def prefilter() -> None:
    """Run the free keyword prefilter on new sources."""
    from techbio.ledger.extract import run_prefilter

    console.print(run_prefilter(get_engine()))


@app.command()
def extract(
    execute: Annotated[
        bool, typer.Option("--execute", help="spend money (default is a dry run)")
    ] = False,
    approval: Annotated[
        str | None, typer.Option(help="operator's explicit go-ahead, recorded verbatim")
    ] = None,
    limit: Annotated[int | None, typer.Option(help="at most N documents (newest first)")] = None,
    job_kind: Annotated[
        str, typer.Option(help="budget line in config/budget.yaml")
    ] = "ledger_extract",
) -> None:
    """Two-model extraction with tie-break and human queue. Dry run unless --execute."""
    from techbio.ledger.extract import run_extraction

    out = run_extraction(
        get_engine(), execute=execute, approval=approval, limit=limit, job_kind=job_kind
    )
    console.print(json.dumps(out, indent=1, default=str))


@app.command()
def review(
    reviewer: Annotated[
        str, typer.Option(help="your handle, recorded on every label")
    ] = "operator",
) -> None:
    """Work through the human review queue."""
    from techbio.ledger.review import interactive

    console.print(interactive(get_engine(), reviewer))


@app.command()
def report(as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Summary: universe, sources, events, 90-day scope, queue size, slips, spend."""
    from techbio.ledger.report import summary

    s = summary(get_engine())
    console.print_json(json.dumps(s, default=str)) if as_json else console.print(s)


@app.command()
def sample(
    out: Annotated[Path, typer.Option()] = Path("docs/milestones/ledger-v0/sample_events.csv"),
    n: int = 25,
) -> None:
    """Write sample rows (structured facts and links only) for the milestone write-up."""
    from techbio.ledger.report import write_sample

    console.print(f"wrote {write_sample(get_engine(), out, n)} rows to {out}")

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
def report(
    as_json: Annotated[bool, typer.Option("--json")] = False,
    drops: Annotated[int, typer.Option(help="quote drops to sample for the spot-check")] = 10,
) -> None:
    """Summary: universe, sources, events, 90-day scope, queue size, slips, quote drops, spend.

    The JSON form is shareable. The plain form also prints a random sample of quote drops, which
    shows source text: it is for the operator's terminal only, never for a PR or an export."""
    from techbio.ledger.quotes import drop_sample
    from techbio.ledger.report import summary

    engine = get_engine()
    s = summary(engine)
    if as_json:
        console.print_json(json.dumps(s, default=str))
        return
    console.print(s)
    sample = drop_sample(engine, n=drops)
    console.rule(f"quote drops: random sample of {len(sample)} (local only: contains source text)")
    for d in sample:
        st = d["statement"] or {}
        console.print(
            f"[bold]{d['reject_reason']}[/] score {d['score']:.2f} · {d['model_key']} · "
            f"{st.get('event_type')} {st.get('asset_name')} {st.get('kind')} · {d['url']}"
        )
        console.print(f"  claimed: {d['claimed_quote']}")
        console.print(f"  nearest: {d['nearest_span']}")


@app.command()
def sample(
    out: Annotated[Path, typer.Option()] = Path("docs/milestones/ledger-v0/sample_events.csv"),
    n: int = 25,
) -> None:
    """Write sample rows and the exclusion list (structured facts and links only)."""
    from techbio.ledger.report import write_exclusions, write_sample

    engine = get_engine()
    console.print(f"wrote {write_sample(engine, out, n)} rows to {out}")
    ex = out.with_name("exclusions.csv")
    console.print(f"wrote {write_exclusions(engine, ex)} exclusions to {ex}")

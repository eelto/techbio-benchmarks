"""`techbio` CLI: database, spend, and the package sub-commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from techbio.ledger.cli import app as ledger_app

app = typer.Typer(no_args_is_help=True)
db = typer.Typer(no_args_is_help=True, help="Database migrations.")
app.add_typer(db, name="db")
app.add_typer(ledger_app, name="ledger")
console = Console()


def _alembic_cfg():
    from alembic.config import Config

    from techbio.core.config import project_root, settings

    cfg = Config(str(project_root() / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root() / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings().db_url)
    return cfg


@db.command()
def upgrade(revision: str = "head") -> None:
    from alembic import command

    command.upgrade(_alembic_cfg(), revision)
    console.print(f"database at {revision}")


@app.command()
def spend(days: Annotated[int, typer.Option()] = 30) -> None:
    """Spend ledger for the last N days."""
    from techbio.core.db import get_engine
    from techbio.core.spend import spend_report

    rows = spend_report(get_engine(), days)
    total = sum(r["actual_usd"] for r in rows)
    for r in rows:
        console.print(
            f"{r['started_at']:%Y-%m-%d %H:%M} {r['job_kind']:<18} {r['status']:<14} est ${r['est_usd']:.2f} actual ${r['actual_usd']:.2f} cap ${r['cap_usd']:.2f} ({r['approval']})"
        )
    console.print(f"total ${total:.2f} over {days} days")

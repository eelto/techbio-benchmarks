"""Spend guard (critical piece 6).

Rules (CLAUDE.md, Budget):
- Every paid job is a dry run unless `execute=True`. The dry run prints estimated calls and USD.
- Executing needs an approval: an explicit one from the operator (recorded verbatim), or a standing
  approval in config/budget.yaml whose scope covers the job and whose day/month allowance still
  fits the estimate.
- The per-job hard cap comes from config/budget.yaml. An estimate over the cap is refused.
- During the run, every request reserves its worst-case cost before it is sent. A request that
  would push actual + reserved past the cap is never sent, so the job halts at the cap.
- A spend summary is printed and stored after every job.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from rich.console import Console
from rich.table import Table as RichTable
from sqlalchemy import Engine, func, insert, select, update

from techbio.core.config import load_yaml
from techbio.core.db import spend_ledger
from techbio.core.ids import new_id

console = Console(stderr=True)


class DryRun(Exception):
    """Raised by authorize() when the job was not asked to execute. Not an error."""


class SpendRefused(Exception):
    pass


class CapExceeded(Exception):
    pass


def price_tokens(
    model: dict[str, Any],
    tokens_in: int,
    tokens_out: int,
    tokens_cached_in: int = 0,
    batch: bool = True,
) -> float:
    """USD for one call (or an aggregate) at list price, with the batch discount if used.

    `tokens_out` includes reasoning tokens: every provider bills them as output.
    """
    p = model["price"]
    uncached = max(tokens_in - tokens_cached_in, 0)
    usd = (
        uncached * p["input"]
        + tokens_cached_in * p.get("cached_input", p["input"])
        + tokens_out * p["output"]
    ) / 1e6
    if batch:
        usd *= model.get("batch_discount", 1.0)
    return usd


@dataclass
class LineItem:
    model_key: str
    model_version: str
    n_calls: int
    n_cached: int
    tokens_in: int
    tokens_out: int
    usd: float


@dataclass
class Estimate:
    job_kind: str
    items: list[LineItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_usd(self) -> float:
        return round(sum(i.usd for i in self.items), 4)

    @property
    def n_calls(self) -> int:
        return sum(i.n_calls for i in self.items)

    def render(self, cap_usd: float | None = None) -> RichTable:
        t = RichTable(title=f"Estimate · {self.job_kind}")
        for col in ("model", "calls", "cached (free)", "tokens in", "tokens out", "USD"):
            t.add_column(col, justify="right" if col != "model" else "left")
        for i in self.items:
            t.add_row(
                f"{i.model_key} ({i.model_version})",
                f"{i.n_calls:,}",
                f"{i.n_cached:,}",
                f"{i.tokens_in:,}",
                f"{i.tokens_out:,}",
                f"${i.usd:,.2f}",
            )
        t.add_row("total", f"{self.n_calls:,}", "", "", "", f"${self.total_usd:,.2f}")
        if cap_usd is not None:
            t.caption = f"cap ${cap_usd:,.2f}" + (
                " · " + " · ".join(self.notes) if self.notes else ""
            )
        return t


def job_cap(job_kind: str) -> float:
    jobs = load_yaml("budget").get("jobs", {})
    if job_kind not in jobs:
        raise SpendRefused(f"job kind {job_kind!r} has no cap in config/budget.yaml")
    return float(jobs[job_kind]["cap_usd"])


def _spent_since(engine: Engine, since: datetime, job_kinds: list[str] | None = None) -> float:
    q = select(func.coalesce(func.sum(spend_ledger.c.actual_usd), 0.0)).where(
        spend_ledger.c.started_at >= since
    )
    if job_kinds is not None:
        q = q.where(spend_ledger.c.job_kind.in_(job_kinds))
    with engine.connect() as conn:
        return float(conn.execute(q).scalar_one())


def standing_approval_for(
    engine: Engine, job_kind: str, est_usd: float, at: datetime
) -> tuple[str | None, str]:
    """Return (approval_ref, reason). approval_ref is None when no standing approval fits."""
    day0 = at.replace(hour=0, minute=0, second=0, microsecond=0)
    month0 = day0.replace(day=1)
    for sa in load_yaml("budget").get("standing_approvals", []):
        scope = sa.get("scope", [])
        if job_kind not in scope:
            continue
        today = _spent_since(engine, day0, scope)
        month = _spent_since(engine, month0, scope)
        if today + est_usd > sa["per_day_usd"]:
            return None, (
                f"standing approval {sa['id']}: ${today:.2f} spent today + ${est_usd:.2f} "
                f"> ${sa['per_day_usd']:.2f}/day"
            )
        if month + est_usd > sa["per_month_usd"]:
            return None, (
                f"standing approval {sa['id']}: ${month:.2f} spent this month + "
                f"${est_usd:.2f} > ${sa['per_month_usd']:.2f}/month"
            )
        return f"standing:{sa['id']}", "fits standing approval"
    return None, f"no standing approval covers {job_kind!r}"


class SpendGuard:
    def __init__(
        self,
        engine: Engine,
        job_kind: str,
        run_id: str,
        *,
        execute: bool = False,
        approval: str | None = None,
    ) -> None:
        self.engine = engine
        self.job_kind = job_kind
        self.run_id = run_id
        self.execute = execute
        self.explicit_approval = approval
        self.cap_usd = job_cap(job_kind)
        self.job_id = new_id("job")
        self.estimate: Estimate | None = None
        self.approval_ref: str | None = None
        self.actual_usd = 0.0
        self.reserved_usd = 0.0
        self.n_calls = 0
        self.n_cached = 0
        self.by_model: dict[str, dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "cached": 0, "tokens_in": 0, "tokens_out": 0, "usd": 0.0}
        )
        self._started = False

    # -- before the job ------------------------------------------------------

    def authorize(self, estimate: Estimate, at: datetime | None = None) -> None:
        """Print the estimate; raise DryRun unless executing; raise SpendRefused unless approved."""
        at = at or datetime.now(UTC)
        self.estimate = estimate
        console.print(estimate.render(self.cap_usd))
        if not self.execute:
            raise DryRun(
                f"dry run: {estimate.n_calls:,} calls, est ${estimate.total_usd:,.2f} "
                f"(cap ${self.cap_usd:,.2f}). Re-run with --execute and an approval to spend."
            )
        if estimate.total_usd > self.cap_usd:
            raise SpendRefused(
                f"estimate ${estimate.total_usd:,.2f} exceeds the {self.job_kind} cap "
                f"${self.cap_usd:,.2f}"
            )
        monthly_cap = load_yaml("budget").get("monthly_operating_cap_usd")
        if monthly_cap is not None and self.job_kind.startswith(("ledger", "arena")):
            month0 = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            spent = _spent_since(self.engine, month0)
            if spent + estimate.total_usd > monthly_cap:
                raise SpendRefused(
                    f"monthly operating cap: ${spent:,.2f} spent + ${estimate.total_usd:,.2f} "
                    f"> ${monthly_cap:,.2f}"
                )
        if self.explicit_approval:
            self.approval_ref = f"explicit:{self.explicit_approval}"
        else:
            ref, reason = standing_approval_for(self.engine, self.job_kind, estimate.total_usd, at)
            if ref is None:
                raise SpendRefused(f"not approved: {reason}. Ask the operator for a go-ahead.")
            self.approval_ref = ref
        with self.engine.begin() as conn:
            conn.execute(
                insert(spend_ledger).values(
                    job_id=self.job_id,
                    run_id=self.run_id,
                    job_kind=self.job_kind,
                    approval=self.approval_ref,
                    est_usd=estimate.total_usd,
                    cap_usd=self.cap_usd,
                    actual_usd=0.0,
                    n_calls=0,
                    n_cached=0,
                    by_model={},
                    status="running",
                    started_at=at,
                )
            )
        self._started = True
        console.print(f"[green]approved[/] ({self.approval_ref}); job {self.job_id}")

    # -- during the job ------------------------------------------------------

    def reserve(self, usd: float) -> None:
        """Reserve worst-case cost before sending a request. Raises CapExceeded instead of sending."""
        if not self._started:
            raise SpendRefused("reserve() before authorize()")
        if self.actual_usd + self.reserved_usd + usd > self.cap_usd + 1e-9:
            raise CapExceeded(
                f"cap ${self.cap_usd:,.2f} reached: actual ${self.actual_usd:,.2f} + reserved "
                f"${self.reserved_usd:,.2f} + next ${usd:,.4f}"
            )
        self.reserved_usd += usd

    def release(self, usd: float) -> None:
        self.reserved_usd = max(self.reserved_usd - usd, 0.0)

    def settle(
        self,
        model_key: str,
        reserved_usd: float,
        actual_usd: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cached: bool = False,
    ) -> None:
        self.release(reserved_usd)
        m = self.by_model[model_key]
        m["calls"] += 1
        if cached:
            self.n_cached += 1
            m["cached"] += 1
            return
        self.n_calls += 1
        self.actual_usd += actual_usd
        m["tokens_in"] += tokens_in
        m["tokens_out"] += tokens_out
        m["usd"] += actual_usd

    def record_cached(self, model_key: str) -> None:
        self.settle(model_key, 0.0, 0.0, cached=True)

    # -- after the job -------------------------------------------------------

    def finish(self, status: str = "finished") -> dict[str, Any]:
        summary = {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "job_kind": self.job_kind,
            "approval": self.approval_ref,
            "est_usd": self.estimate.total_usd if self.estimate else 0.0,
            "actual_usd": round(self.actual_usd, 4),
            "cap_usd": self.cap_usd,
            "n_calls": self.n_calls,
            "n_cached": self.n_cached,
            "by_model": {k: dict(v) for k, v in self.by_model.items()},
            "status": status,
        }
        if self._started:
            with self.engine.begin() as conn:
                conn.execute(
                    update(spend_ledger)
                    .where(spend_ledger.c.job_id == self.job_id)
                    .values(
                        actual_usd=summary["actual_usd"],
                        n_calls=self.n_calls,
                        n_cached=self.n_cached,
                        by_model=summary["by_model"],
                        status=status,
                        finished_at=datetime.now(UTC),
                    )
                )
        console.print(
            f"[bold]Spend summary[/] {self.job_kind} {self.run_id}: actual "
            f"${summary['actual_usd']:,.2f} of est ${summary['est_usd']:,.2f} (cap "
            f"${self.cap_usd:,.2f}); {self.n_calls:,} paid calls, {self.n_cached:,} cached; "
            f"status {status}"
        )
        return summary


def spend_report(engine: Engine, days: int = 30) -> list[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    with engine.connect() as conn:
        rows = conn.execute(
            select(spend_ledger)
            .where(spend_ledger.c.started_at >= since)
            .order_by(spend_ledger.c.started_at)
        ).mappings()
        return [dict(r) for r in rows]

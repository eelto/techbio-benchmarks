from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from techbio.core.db import spend_ledger
from techbio.core.spend import CapExceeded, DryRun, Estimate, LineItem, SpendGuard, SpendRefused


def est(usd, kind="ledger_extract"):
    return Estimate(kind, [LineItem("extractor_a", "m", 10, 0, 1000, 1000, usd)])


def test_dry_run_is_the_default(engine):
    g = SpendGuard(engine, "ledger_extract", "r1")
    with pytest.raises(DryRun):
        g.authorize(est(0.5))
    with engine.connect() as c:
        assert c.execute(select(spend_ledger)).first() is None  # nothing recorded, nothing spent


def test_over_cap_estimate_is_refused(engine):
    g = SpendGuard(engine, "ledger_bootstrap", "r1", execute=True, approval="operator: go")
    with pytest.raises(SpendRefused, match="exceeds"):
        g.authorize(est(80.0, "ledger_bootstrap"))  # cap $75


def test_unknown_job_kind_is_refused(engine):
    with pytest.raises(SpendRefused):
        SpendGuard(engine, "something_new", "r1", execute=True)


def test_standing_approval_covers_small_ingest(engine):
    g = SpendGuard(engine, "ledger_extract", "r1", execute=True)
    g.authorize(est(0.40), at=datetime(2026, 10, 30, 12, tzinfo=UTC))
    assert g.approval_ref == "standing:sa-2026-10-30-ingest"


def test_bootstrap_needs_explicit_approval(engine):
    g = SpendGuard(engine, "ledger_bootstrap", "r1", execute=True)
    with pytest.raises(SpendRefused, match="not approved"):
        g.authorize(est(44.0, "ledger_bootstrap"))
    g2 = SpendGuard(
        engine,
        "ledger_bootstrap",
        "r2",
        execute=True,
        approval="operator 2026-10-30: go on bootstrap",
    )
    g2.authorize(est(44.0, "ledger_bootstrap"))
    assert g2.approval_ref.startswith("explicit:operator")


def test_daily_standing_allowance_is_enforced(engine):
    at = datetime(2026, 10, 30, 12, tzinfo=UTC)
    g = SpendGuard(engine, "ledger_extract", "r1", execute=True)
    g.authorize(est(2.5), at=at)
    g.settle("extractor_a", 0.0, 2.5, 1, 1)
    g.finish()
    g2 = SpendGuard(engine, "ledger_extract", "r2", execute=True)
    with pytest.raises(SpendRefused, match=r"/day"):
        g2.authorize(est(1.0), at=at)


def test_reserve_halts_at_cap_and_summary_is_stored(engine):
    g = SpendGuard(engine, "ledger_extract", "r1", execute=True)
    g.authorize(est(1.0))
    g.reserve(2.0)
    g.settle("extractor_a", 2.0, 1.9, 100, 100)
    with pytest.raises(CapExceeded):
        g.reserve(1.5)  # 1.9 actual + 1.5 > $3 cap: never sent
    s = g.finish("halted_at_cap")
    assert s["actual_usd"] == pytest.approx(1.9)
    with engine.connect() as c:
        row = c.execute(select(spend_ledger)).mappings().one()
    assert row["status"] == "halted_at_cap" and row["actual_usd"] == pytest.approx(1.9)

"""scope check: review_queue.reason gains 'scope_check'

A Phase 2 readout is checked against the registry before it reaches the ledger (ledger/scope.py).
Statements the registry rules out are recorded as closed items; unconfirmed ones go to the operator.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-01 16:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVIEW_REASONS_V3 = (
    "disagreement",
    "low_confidence",
    "quote_unverified",
    "event_link_ambiguous",
    "tiebreak_abstained",
    "operator_flag",
    "outcome_confirmation",
    "parse_failed",
    "exclusion_link",
    "scope_check",
)


def _replace_check(table: str, column: str, values: tuple[str, ...]) -> None:
    name = f"ck_{table}_{column}"
    with op.batch_alter_table(table, schema=None) as batch_op:
        batch_op.drop_constraint(op.f(name), type_="check")
        batch_op.create_check_constraint(
            op.f(name), f"{column} IN ({', '.join(repr(v) for v in values)})"
        )


def upgrade() -> None:
    _replace_check("review_queue", "reason", REVIEW_REASONS_V3)


def downgrade() -> None:
    op.execute("DELETE FROM review_queue WHERE reason = 'scope_check'")
    _replace_check("review_queue", "reason", REVIEW_REASONS_V3[:-1])

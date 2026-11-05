"""Audit of the ledger's agreed outcomes (decisions V.2 and V.3, operator 2026-11-05).

Two extractors from different vendors agreeing is enough to accept an outcome (V.1). The audit
checks that path: a random sample of agreed outcomes, drawn with the seed fixed in
`config/audit.yaml` before the bootstrap extraction runs, is read first by Claude without the
extractors' answer and then verified by the operator. The operator's verdict is the label of
record and the error count that is published; the pass bar is set in advance.
"""

from __future__ import annotations

import random
from typing import Any

from sqlalchemy import Connection, and_, func, select

from techbio.core.config import load_yaml
from techbio.core.db import labels


def settings(name: str = "bootstrap") -> dict[str, Any]:
    return load_yaml("audit")[name]


def agreed_outcomes(conn: Connection) -> list[dict[str, Any]]:
    """Every event whose current result was accepted by agreement, once each, in label order. An
    outcome the operator or the tie-breaker has since set is not in the pool."""
    latest = (
        select(labels.c.event_id, func.max(labels.c.version).label("version"))
        .where(labels.c.field == "result_category")
        .group_by(labels.c.event_id)
        .subquery()
    )
    q = (
        select(labels)
        .join(
            latest,
            and_(labels.c.event_id == latest.c.event_id, labels.c.version == latest.c.version),
        )
        .where(labels.c.field == "result_category", labels.c.reviewer_kind == "auto-agreement")
        .order_by(labels.c.label_id)
    )
    return [dict(r) for r in conn.execute(q).mappings()]


def draw(conn: Connection, n: int, seed: int) -> list[dict[str, Any]]:
    """The sample: `n` agreed outcomes chosen by `seed`, or all of them if there are fewer."""
    pool = agreed_outcomes(conn)
    return random.Random(seed).sample(pool, min(n, len(pool)))


def passes(errors: int, cfg: dict[str, Any]) -> bool:
    """V.3: the operator's error count against the bar set in advance."""
    return errors <= cfg["pass_max_errors"]

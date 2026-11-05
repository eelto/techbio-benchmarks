"""Small write helpers shared by the ingest modules."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, select, update

from techbio.core.db import now, sources, sponsors
from techbio.core.http import FetchResult
from techbio.core.ids import new_id


def upsert_source(
    conn: Connection,
    fr: FetchResult,
    *,
    type: str,
    url: str | None = None,
    sponsor_id: str | None = None,
    published_at: datetime | None = None,
    title: str | None = None,
    meta: dict[str, Any] | None = None,
    is_primary: bool = True,
) -> tuple[str, bool]:
    """Insert a source version (url, sha256) if new. Returns (source_id, created)."""
    url = url or fr.url
    row = conn.execute(
        select(sources.c.source_id).where(sources.c.url == url, sources.c.sha256 == fr.sha256)
    ).first()
    if row:
        return row.source_id, False
    sid = new_id("src")
    conn.execute(
        sources.insert().values(
            source_id=sid,
            url=url,
            type=type,
            sponsor_id=sponsor_id,
            is_primary=is_primary,
            title=title,
            published_at=published_at,
            retrieved_at=fr.retrieved_at,
            sha256=fr.sha256,
            local_path=str(fr.local_path),
            content_type=fr.content_type,
            meta=meta or {},
            prefilter_status="pending",
            extract_status="none",
            created_recorded_at=now(),
        )
    )
    return sid, True


def upsert_sponsor(
    conn: Connection,
    *,
    cik: int,
    name: str,
    tickers: list[str],
    exchange: str | None,
    sic: int | None,
    filer_kind: str | None = None,
    as_of: date | None = None,
) -> str:
    row = conn.execute(select(sponsors).where(sponsors.c.cik == cik)).mappings().first()
    t = now()
    if row:
        changes: dict[str, Any] = {}
        if sorted(row["tickers"]) != sorted(tickers):
            changes["tickers"] = tickers
        for k, v in (
            ("name", name),
            ("exchange", exchange),
            ("sic", sic),
            ("filer_kind", filer_kind),
        ):
            if v is not None and row[k] != v:
                changes[k] = v
        if row["in_universe_to"] is not None:
            changes["in_universe_to"] = None
        if changes:
            changes["updated_recorded_at"] = t
            conn.execute(update(sponsors).where(sponsors.c.cik == cik).values(**changes))
        return row["sponsor_id"]
    sid = new_id("spn")
    conn.execute(
        sponsors.insert().values(
            sponsor_id=sid,
            name=name,
            cik=cik,
            tickers=tickers,
            exchange=exchange,
            filer_kind=filer_kind,
            sic=sic,
            in_universe_from=as_of or t.date(),
            in_universe_to=None,
            created_recorded_at=t,
            updated_recorded_at=t,
        )
    )
    return sid

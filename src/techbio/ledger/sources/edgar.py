"""EDGAR: the sponsor universe and its 8-K / 6-K press-release exhibits.

Universe (Q-A1, decided): Nasdaq, NYSE or NYSE American listings in the SEC tickers file, whose SIC
is 2834, 2835, 2836 or 8731, plus the curated add list, minus the drop list. SIC membership comes
from EDGAR's company browse by SIC (about 60 requests) and is confirmed from each company's
submissions JSON.

Filings: the per-CIK submissions API is the backbone. 8-Ks are kept when their items include 7.01,
8.01 or 2.02 (Reg FD, other events, earnings); 6-Ks have no items and are kept whole (the prefilter
does the filtering). From each kept filing we fetch the EX-99.x exhibits (and the 6-K body).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from lxml import html as lxml_html
from rich.console import Console
from sqlalchemy import Engine, select

from techbio.core.config import load_yaml
from techbio.core.db import sponsors
from techbio.core.http import Fetcher
from techbio.ledger.store import upsert_source, upsert_sponsor

console = Console(stderr=True)
BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar"
FPI_FORMS = {"6-K", "20-F", "40-F", "6-K/A", "20-F/A"}


def _cfg() -> dict[str, Any]:
    return load_yaml("sources")


def ciks_for_sic(fetcher: Fetcher, sic: int) -> set[int]:
    out: set[int] = set()
    start = 0
    while True:
        fr = fetcher.get(
            BROWSE,
            params={
                "action": "getcompany",
                "SIC": str(sic),
                "owner": "include",
                "count": "100",
                "start": str(start),
            },
            max_age=timedelta(days=7),
        )
        doc = lxml_html.fromstring(fr.content)
        rows = doc.xpath("//table[contains(@class,'tableFile2')]//tr[td]")
        for tr in rows:
            link = tr.xpath("./td[1]//a/text()")
            if link and link[0].strip().isdigit():
                out.add(int(link[0].strip()))
        if len(rows) < 100:
            return out
        start += 100


def build_universe(engine: Engine, fetcher: Fetcher) -> dict[str, int]:
    cfg = _cfg()
    uni = cfg["universe"]
    tick = fetcher.get(cfg["sec"]["tickers_url"], max_age=timedelta(hours=20)).json()
    idx = {f: i for i, f in enumerate(tick["fields"])}
    listed: dict[int, dict[str, Any]] = {}
    exchanges_seen: dict[str, int] = {}
    for row in tick["data"]:
        ex = row[idx["exchange"]] or ""
        exchanges_seen[ex] = exchanges_seen.get(ex, 0) + 1
        if ex not in uni["exchanges"]:
            continue
        cik = int(row[idx["cik"]])
        rec = listed.setdefault(cik, {"name": row[idx["name"]], "tickers": [], "exchange": ex})
        rec["tickers"].append(row[idx["ticker"]])
    console.print(f"tickers file exchanges: {exchanges_seen}")
    sic_of: dict[int, int] = {}
    for sic in uni["sic_codes"]:
        for cik in ciks_for_sic(fetcher, sic):
            sic_of[cik] = sic
    members = {c for c in listed if c in sic_of} | {int(c) for c in uni.get("add", [])}
    members -= {int(c) for c in uni.get("drop", [])}
    stats = {"listed": len(listed), "sic_ciks": len(sic_of), "members": 0}
    with engine.begin() as conn:
        for cik in sorted(members):
            rec = listed.get(cik)
            if rec is None:
                continue  # an add-list CIK that isn't listed on an allowed exchange
            upsert_sponsor(
                conn,
                cik=cik,
                name=rec["name"],
                tickers=rec["tickers"],
                exchange=rec["exchange"],
                sic=sic_of.get(cik),
            )
            stats["members"] += 1
        # Companies that left the universe keep their history; mark the end date.
        for row in conn.execute(
            select(sponsors.c.sponsor_id, sponsors.c.cik, sponsors.c.in_universe_to)
        ).all():
            if row.cik not in members and row.in_universe_to is None:
                conn.execute(
                    sponsors.update()
                    .where(sponsors.c.sponsor_id == row.sponsor_id)
                    .values(in_universe_to=date.today())
                )
    return stats


def _filings(sub: dict[str, Any]) -> list[dict[str, Any]]:
    r = sub["filings"]["recent"]
    keys = (
        "accessionNumber",
        "filingDate",
        "acceptanceDateTime",
        "form",
        "items",
        "primaryDocument",
        "primaryDocDescription",
    )
    return [
        dict(zip(keys, vals, strict=True))
        for vals in zip(*(r.get(k, [""] * len(r["form"])) for k in keys), strict=True)
    ]


def exhibit_docs(fetcher: Fetcher, cik: int, accession: str) -> list[dict[str, str]]:
    """Rows of the filing index whose type is EX-99*, plus the main document for 6-Ks."""
    acc_nodash = accession.replace("-", "")
    url = f"{_cfg()['sec']['archives_base']}/{cik}/{acc_nodash}/{accession}-index.htm"
    fr = fetcher.get(url, max_age=timedelta(days=365))
    doc = lxml_html.fromstring(fr.content)
    out: list[dict[str, str]] = []
    for tr in doc.xpath("//table[contains(@class,'tableFile')]//tr[td]"):
        tds = tr.xpath("./td")
        if len(tds) < 4:
            continue
        typ = tds[3].text_content().strip()
        href = (tds[2].xpath(".//a/@href") or [""])[0].replace("/ix?doc=", "")
        if not href or not href.lower().endswith((".htm", ".html", ".txt")):
            continue
        out.append(
            {
                "type": typ,
                "description": tds[1].text_content().strip(),
                "url": "https://www.sec.gov" + href,
            }
        )
    return out


def ingest_sponsor(
    engine: Engine, fetcher: Fetcher, sponsor_id: str, cik: int, since: date
) -> dict[str, int]:
    cfg = _cfg()
    sub = fetcher.get(
        cfg["sec"]["submissions_url"].format(cik=cik), max_age=timedelta(hours=20)
    ).json()
    forms = set(cfg["edgar"]["forms"])
    items_keep = set(cfg["edgar"]["eightk_items"])
    filer_kind = (
        "fpi" if any(f in FPI_FORMS for f in sub["filings"]["recent"]["form"]) else "domestic"
    )
    stats = {"filings": 0, "docs": 0, "new_docs": 0}
    with engine.begin() as conn:
        conn.execute(
            sponsors.update()
            .where(sponsors.c.sponsor_id == sponsor_id)
            .values(filer_kind=filer_kind, sic=int(sub.get("sic") or 0) or None)
        )
    for f in _filings(sub):
        if f["form"] not in forms or date.fromisoformat(f["filingDate"]) < since:
            continue
        if f["form"].startswith("8-K") and not (
            set(re.split(r"[,\s]+", f["items"] or "")) & items_keep
        ):
            continue
        stats["filings"] += 1
        accepted = datetime.fromisoformat(
            f["acceptanceDateTime"].replace("Z", "+00:00")
        ).astimezone(UTC)
        kind = "edgar_6k" if f["form"].startswith("6-K") else "edgar_8k"
        for ex in exhibit_docs(fetcher, cik, f["accessionNumber"]):
            is_ex99 = ex["type"].upper().startswith("EX-99")
            is_6k_body = kind == "edgar_6k" and ex["type"].upper().startswith("6-K")
            if not (is_ex99 or is_6k_body):
                continue
            fr = fetcher.get(ex["url"], max_age=timedelta(days=3650))
            stats["docs"] += 1
            with engine.begin() as conn:
                _, created = upsert_source(
                    conn,
                    fr,
                    type=kind,
                    url=ex["url"],
                    sponsor_id=sponsor_id,
                    published_at=accepted,
                    title=ex["description"] or f["primaryDocDescription"],
                    meta={
                        "cik": cik,
                        "accession": f["accessionNumber"],
                        "form": f["form"],
                        "items": f["items"],
                        "exhibit_type": ex["type"],
                        "filing_date": f["filingDate"],
                    },
                )
            stats["new_docs"] += int(created)
    return stats


def ingest(
    engine: Engine, fetcher: Fetcher, lookback_days: int | None = None, limit: int | None = None
) -> dict[str, int]:
    days = lookback_days or _cfg()["edgar"]["lookback_days"]
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    with engine.connect() as conn:
        rows = conn.execute(
            select(sponsors.c.sponsor_id, sponsors.c.cik)
            .where(sponsors.c.in_universe_to.is_(None))
            .order_by(sponsors.c.cik)
        ).all()
    total = {"sponsors": 0, "filings": 0, "docs": 0, "new_docs": 0}
    for i, r in enumerate(rows[:limit] if limit else rows):
        try:
            s = ingest_sponsor(engine, fetcher, r.sponsor_id, r.cik, since)
        except Exception as e:  # one bad filer must not stop the run; it is reported
            console.print(f"[red]CIK {r.cik}: {e}[/]")
            continue
        total["sponsors"] += 1
        for k in ("filings", "docs", "new_docs"):
            total[k] += s[k]
        if i % 50 == 0:
            console.print(f"edgar: {i}/{len(rows)} sponsors, {total['docs']} docs")
    return total

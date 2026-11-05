"""FDA advisory committee meetings from the Federal Register API (public domain).

Meeting notices name the application (NDA/BLA number), the product and the sponsor in the Agenda
paragraph, and the date in DATES. These are parsed deterministically, so AdCom events need no model
call. Device panels are out of scope (Q-A3). Cancellation notices void the event.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Engine

from techbio.core.config import load_yaml
from techbio.core.http import Fetcher
from techbio.ledger.store import upsert_source
from techbio.ledger.timing import MONTHS

APP_RE = re.compile(
    r"(?:new drug application|biologics license application|supplemental new drug application|"
    r"supplemental biologics license application)s?\s*\((s?NDA|s?BLA)\)\s*(\d{6})"
    r"(?P<rest>.{0,600}?)(?=\.\s+The proposed|\.\s+FDA intends|\.?$)",
    re.I | re.S,
)
FOR_RE = re.compile(
    r",?\s*for\s+(?P<drug>.+?),\s*(?:submitted|sponsored)\s+by\s+(?P<sponsor>.+)$", re.I | re.S
)
FROM_RE = re.compile(
    r",?\s*from\s+(?P<sponsor>.+?)\s+for\s+(?P<drug>.+?)(?:,?\s+(?:for\s+)?the\s+treatment\b.*)?$",
    re.I | re.S,
)
DATE_CHANGE_RE = re.compile(
    r"(?:changed|rescheduled|moved) to (?:\w+day, )?([A-Z][a-z]+)\.? (\d{1,2}),? (20\d{2})"
)
DATE_RE = re.compile(r"held on (?:\w+day, )?([A-Z][a-z]+)\.? (\d{1,2}),? (20\d{2})")
INDICATION_RE = re.compile(
    r"proposed indication(?: \(use\))? (?:for this product )?is (?:for )?(?P<ind>.+?)\.\s",
    re.I | re.S,
)


def _clean(s: str) -> str:
    return " ".join(s.split())


def parse_notice(text: str, title: str = "") -> dict[str, Any]:
    """Return {'meeting_date', 'applications': [{kind, number, drug, sponsor, indication}],
    'cancelled', 'amended'}. Cancellation and amendment are read from the title only (the body of
    every notice says what happens "in the event that the meeting is cancelled")."""
    body = _clean(text)
    out: dict[str, Any] = {
        "meeting_date": None,
        "applications": [],
        "cancelled": "cancellation" in title.lower(),
        "amended": "amendment of notice" in title.lower(),
    }
    m = DATE_CHANGE_RE.search(body) or DATE_RE.search(body)
    if m and m.group(1).lower() in MONTHS:
        out["meeting_date"] = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    agenda = body.split("Agenda:", 1)[1] if "Agenda:" in body else ""
    agenda = agenda.split("Procedure:", 1)[0]
    # Fall back to the title, which names the application on product-specific notices.
    title_app = title.split("-", 1)[1] if "-" in title else ""
    seen: set[str] = set()
    for am in [*APP_RE.finditer(agenda), *APP_RE.finditer(title_app + ".")]:
        if am.group(2) in seen:
            continue
        seen.add(am.group(2))
        kind, number, rest = am.group(1), am.group(2), am.group("rest")
        kind = kind.upper()
        kind = "s" + kind[1:] if kind.startswith("S") else kind
        app = {"kind": kind, "number": number, "drug": None, "sponsor": None, "indication": None}
        fm = FOR_RE.search(rest)
        if fm:
            app["drug"] = fm.group("drug").strip(" ,")
            # Sponsor runs to the sentence end; tolerate "Sydnexis. Inc." style typos.
            sp = re.split(r"\.\s+(?=The |FDA |On |In )", fm.group("sponsor"))[0]
            app["sponsor"] = sp.strip(" .,")
        elif fr := FROM_RE.search(rest):
            app["sponsor"] = fr.group("sponsor").strip(" .,")
            app["drug"] = fr.group("drug").strip(" .,")
        im = INDICATION_RE.search(agenda[am.end() : am.end() + 800] + " ")
        if im:
            app["indication"] = im.group("ind").strip()
        out["applications"].append(app)
    return out


def ingest(engine: Engine, fetcher: Fetcher, lookback_days: int = 365) -> dict[str, int]:
    cfg = load_yaml("sources")["fedreg"]
    since = (datetime.now(UTC) - timedelta(days=lookback_days)).date()
    stats = {"notices": 0, "product_notices": 0, "new_versions": 0}
    page = 1
    while True:
        params = {
            "conditions[agencies][]": cfg["agency"],
            "conditions[type][]": "NOTICE",
            "conditions[term]": '"Advisory Committee"',
            "conditions[publication_date][gte]": since.isoformat(),
            "per_page": "100",
            "page": str(page),
            "order": "oldest",
            "fields[]": [
                "title",
                "publication_date",
                "html_url",
                "raw_text_url",
                "document_number",
            ],
        }
        data = fetcher.get(cfg["base_url"], params=params, max_age=timedelta(hours=20)).json()
        for r in data.get("results", []):
            title = r["title"]
            if (
                not any(
                    k in title for k in ("Notice of Meeting", "Cancellation", "Amendment of Notice")
                )
                or "Devices" in title
            ):
                continue
            stats["notices"] += 1
            fr = fetcher.get(r["raw_text_url"], max_age=timedelta(days=30))
            parsed = parse_notice(fr.text(), title)
            if not parsed["applications"]:
                continue  # topic meetings (e.g. strain selection) are not product events
            stats["product_notices"] += 1
            with engine.begin() as conn:
                _, created = upsert_source(
                    conn,
                    fr,
                    type="fedreg_adcom",
                    url=r["html_url"],
                    published_at=datetime.fromisoformat(r["publication_date"]).replace(tzinfo=UTC),
                    title=title,
                    meta={
                        "document_number": r["document_number"],
                        "raw_text_url": r["raw_text_url"],
                        "meeting_date": parsed["meeting_date"].isoformat()
                        if parsed["meeting_date"]
                        else None,
                        "cancelled": parsed["cancelled"],
                        "amended": parsed["amended"],
                        "applications": parsed["applications"],
                    },
                )
            stats["new_versions"] += int(created)
        if page >= data.get("total_pages", 1):
            break
        page += 1
    return stats

"""ClinicalTrials.gov v2: Phase 2/3 interventional trials led by universe sponsors.

CT.gov records are sponsor-submitted and public domain. Each fetched record version is a source; the
`trials` table holds the current registry facts (design, endpoints, completion dates, stop reasons)
that packs and event matching use. Terminated/suspended/withdrawn trials whose record changed inside
the lookback become extraction inputs (stop reason -> subtype and explanation category).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, update

from techbio.core.config import load_yaml
from techbio.core.db import now, sponsors, trials
from techbio.core.http import Fetcher, FetchResult
from techbio.core.ids import sha256_json
from techbio.ledger.names import same_company, search_term
from techbio.ledger.store import upsert_source

FIELDS = (
    "NCTId,BriefTitle,Acronym,OverallStatus,WhyStopped,PrimaryCompletionDate,"
    "PrimaryCompletionDateType,Phase,StudyType,LeadSponsorName,EnrollmentCount,DesignAllocation,"
    "DesignMasking,Condition,InterventionName,InterventionType,PrimaryOutcomeMeasure,"
    "PrimaryOutcomeTimeFrame,LastUpdatePostDate,StatusVerifiedDate"
)
STOPPED = {"TERMINATED", "SUSPENDED", "WITHDRAWN"}
TWO_B = re.compile(r"\b(?:phase\s*)?(?:2b|iib)\b|pivotal|registrational", re.I)


def in_scope_design(t: dict[str, Any]) -> bool:
    """Taxonomy v1 / Q-B1, as far as the registry can tell: Phase 3 or Phase 2/3; or a randomized
    Phase 2 that is called 2b/pivotal/registrational or enrolls >= 100."""
    phases = set(t.get("phases") or [])
    if "PHASE3" in phases:
        return True
    if "PHASE2" in phases and "PHASE1" not in phases and t.get("allocation") == "RANDOMIZED":
        return (t.get("enrollment") or 0) >= 100 or bool(TWO_B.search(t.get("brief_title") or ""))
    return False


def _query(sponsor_name: str, since: date) -> dict[str, str]:
    return {
        "query.lead": search_term(sponsor_name),
        "filter.advanced": (
            "AREA[StudyType]INTERVENTIONAL AND (AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND "
            f"AREA[LastUpdatePostDate]RANGE[{since.isoformat()},MAX]"
        ),
        "fields": FIELDS,
        "pageSize": "200",
    }


def parse_study(s: dict[str, Any]) -> dict[str, Any]:
    p = s.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    status = p.get("statusModule", {})
    design = p.get("designModule", {})
    pcd = status.get("primaryCompletionDateStruct", {})
    upd = (status.get("lastUpdatePostDateStruct") or {}).get("date")
    return {
        "nct_id": ident.get("nctId"),
        "brief_title": ident.get("briefTitle"),
        "acronym": ident.get("acronym"),
        "lead_sponsor_name": p.get("sponsorCollaboratorsModule", {})
        .get("leadSponsor", {})
        .get("name"),
        "phases": design.get("phases", []),
        "allocation": (design.get("designInfo") or {}).get("allocation"),
        "masking": ((design.get("designInfo") or {}).get("maskingInfo") or {}).get("masking"),
        "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
        "overall_status": status.get("overallStatus"),
        "why_stopped": status.get("whyStopped"),
        "primary_completion_date": pcd.get("date"),
        "primary_completion_type": pcd.get("type"),
        "conditions": p.get("conditionsModule", {}).get("conditions", []),
        "interventions": [
            {"name": i.get("name"), "type": i.get("type")}
            for i in p.get("armsInterventionsModule", {}).get("interventions", [])
        ],
        "primary_outcomes": [
            {"measure": o.get("measure"), "time_frame": o.get("timeFrame")}
            for o in p.get("outcomesModule", {}).get("primaryOutcomes", [])
        ],
        "last_update_posted": date.fromisoformat(upd) if upd else None,
    }


def stop_document(t: dict[str, Any]) -> str:
    """Plain-text rendering of a stopped trial's registry facts, for extraction. Public domain."""
    return "\n".join(
        [
            f"ClinicalTrials.gov record {t['nct_id']} ({t.get('acronym') or 'no acronym'})",
            f"Title: {t.get('brief_title')}",
            f"Lead sponsor: {t.get('lead_sponsor_name')}",
            f"Phase: {', '.join(t.get('phases') or [])}",
            f"Interventions: {', '.join(i['name'] for i in t.get('interventions') or [] if i.get('name'))}",
            f"Conditions: {', '.join(t.get('conditions') or [])}",
            f"Overall status: {t.get('overall_status')}",
            f"Why stopped: {t.get('why_stopped') or '(not given)'}",
            f"Enrollment: {t.get('enrollment')}",
            f"Primary completion: {t.get('primary_completion_date')} ({t.get('primary_completion_type')})",
            f"Record last updated: {t.get('last_update_posted')}",
        ]
    )


def ingest(
    engine: Engine, fetcher: Fetcher, lookback_days: int = 365, limit: int | None = None
) -> dict[str, int]:
    base = load_yaml("sources")["ctgov"]["base_url"]
    since = (datetime.now(UTC) - timedelta(days=lookback_days)).date()
    stats = {"sponsors": 0, "studies": 0, "matched": 0, "new_versions": 0, "stopped_docs": 0}
    with engine.connect() as conn:
        spons = conn.execute(select(sponsors.c.sponsor_id, sponsors.c.name)).all()
    for sp in spons[:limit] if limit else spons:
        stats["sponsors"] += 1
        params = _query(sp.name, since)
        page_token = None
        while True:
            q = dict(params, **({"pageToken": page_token} if page_token else {}))
            fr = fetcher.get(base, params=q, max_age=timedelta(hours=20))
            data = fr.json()
            for study in data.get("studies", []):
                stats["studies"] += 1
                t = parse_study(study)
                if not t["nct_id"] or not t["lead_sponsor_name"]:
                    continue
                if not same_company(t["lead_sponsor_name"], sp.name):
                    continue  # CT.gov search is fuzzy; keep only exact lead-sponsor matches
                stats["matched"] += 1
                created = _store_trial(engine, fetcher, sp.sponsor_id, t, study)
                stats["new_versions"] += created[0]
                stats["stopped_docs"] += created[1]
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return stats


def _store_trial(
    engine: Engine, fetcher: Fetcher, sponsor_id: str, t: dict, study: dict
) -> tuple[int, int]:
    """Store one study record as its own source version and upsert the trials row."""
    url = f"https://clinicaltrials.gov/study/{t['nct_id']}"
    payload = json.dumps(study, sort_keys=True).encode()
    digest = sha256_json(study)
    path = fetcher.raw_dir / digest[:2] / f"{digest}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    fr = FetchResult(
        url=url,
        status=200,
        content=payload,
        sha256=digest,
        local_path=path,
        content_type="application/json",
        retrieved_at=now(),
        from_cache=False,
    )
    stopped = t["overall_status"] in STOPPED and in_scope_design(t)
    pub = (
        datetime.combine(t["last_update_posted"], datetime.min.time(), UTC)
        if t["last_update_posted"]
        else None
    )
    with engine.begin() as conn:
        sid, created = upsert_source(
            conn,
            fr,
            type="ctgov",
            url=url,
            sponsor_id=sponsor_id,
            published_at=pub,
            title=t["brief_title"],
            meta={"nct_id": t["nct_id"], "overall_status": t["overall_status"], "stopped": stopped},
        )
        values = {k: v for k, v in t.items() if k != "nct_id"}
        values.update(sponsor_id=sponsor_id, source_id=sid, updated_recorded_at=now())
        if conn.execute(select(trials.c.nct_id).where(trials.c.nct_id == t["nct_id"])).first():
            conn.execute(update(trials).where(trials.c.nct_id == t["nct_id"]).values(**values))
        else:
            conn.execute(
                trials.insert().values(nct_id=t["nct_id"], created_recorded_at=now(), **values)
            )
    return int(created), int(created and stopped)

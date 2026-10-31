"""End-to-end extraction on synthetic documents with fake providers (no network, no spend)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from techbio.core.db import events, labels, promises, resolutions, review_queue
from techbio.core.llm import runner
from techbio.core.llm.cache import LLMResponse
from techbio.ledger.extract import run_extraction
from techbio.ledger.review import decide, open_items, queue_size

from .conftest import add_source

FIX = Path(__file__).parent / "fixtures"


def st(**kw):
    base = {
        "kind": "guidance",
        "event_type": "readout",
        "asset_name": "zorbalimab",
        "asset_aliases": ["EXT-101"],
        "indication": "atopic dermatitis",
        "nct_id": None,
        "trial_name": "HORIZON-2",
        "phase": "3",
        "application_kind": None,
        "timing_text": "first half of 2027",
        "timing_start": None,
        "timing_end": None,
        "event_date": None,
        "result_category": None,
        "result_subtype": None,
        "sponsor_explanation_category": None,
        "quote": "Topline data are expected in the first half of 2027.",
        "confidence": 0.95,
    }
    base.update(kw)
    return base


SUMMIT_Q = "The Company remains on track to report topline results from the Phase 2b SUMMIT trial in mid-2027."
SUMMIT = dict(
    asset_name="EXT-202",
    asset_aliases=[],
    trial_name="SUMMIT",
    phase="2b",
    indication=None,
    quote=SUMMIT_Q,
)
OUTCOME_HTML = "<html><body><p>Example Therapeutics announced that the Phase 3 HORIZON-2 trial of zorbalimab met its primary endpoint, with a statistically significant improvement in EASI-75 at week 16 (p&lt;0.001).</p></body></html>"
OUTCOME_Q = "the Phase 3 HORIZON-2 trial of zorbalimab met its primary endpoint"


class Fake:
    """Batch + sync provider whose answers depend on (model, source)."""

    def __init__(self, answers):
        self.answers = answers
        self.batches = {}
        self.calls = []

    def _resp(self, key, req, model_key):
        self.calls.append((model_key, req))
        body = self.answers(model_key, req)
        return LLMResponse(key, json.dumps(body), tokens_in=1000, tokens_out=300)

    def submit(self, items, model):
        bid = f"b{len(self.batches)}"
        self.batches[bid] = [self._resp(k, r, r.model_key) for k, r in items]
        return bid

    def collect(self, bid):
        return self.batches[bid]

    def call(self, key, req, model):
        return self._resp(key, req, req.model_key)


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def install(answers):
        f = Fake(answers)
        monkeypatch.setattr(runner, "_provider", lambda model: f)
        holder["f"] = f
        return f

    return install


def answers(model_key, req):
    if model_key == "tiebreak":
        assert (
            "result_category" not in req.user.split("Disputed fields:")[1]
        )  # reserved fields never tie-broken
        return {"choices": [{"field": "window", "choice": "A", "quote": SUMMIT_Q}]}
    if "met its primary endpoint" in req.user:
        cat = "met" if model_key == "extractor_a" else "mixed"
        return {
            "statements": [
                st(
                    kind="outcome",
                    timing_text=None,
                    result_category=cat,
                    event_date="2027-03-02",
                    quote=OUTCOME_Q,
                )
            ]
        }
    out = [st()]
    if model_key == "extractor_a":
        out.append(st(**SUMMIT, timing_text="mid-2027"))
        out.append(
            st(
                asset_name="EXT-303",
                trial_name="DAWN",
                quote="EXT-303 Phase 3 DAWN data expected in 2027.",
            )
        )  # not in the document
    else:
        out.append(st(**SUMMIT, timing_text="second half of 2027"))
    return {"statements": out}


def test_dry_run_makes_no_calls(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )
    out = run_extraction(engine, execute=False)
    assert out["dry_run"] and out["est_usd"] > 0 and f.calls == []


def test_pipeline_routes_agree_tiebreak_queue_and_review(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )
    out = run_extraction(engine, execute=True)
    assert out["accepted"] == 2 and out["tiebreaks"] == 1 and out["quote_dropped"] == 1

    with engine.connect() as c:
        evs = {e["trial_name"]: e for e in c.execute(select(events)).mappings()}
        assert set(evs) == {"HORIZON-2", "SUMMIT"}
        assert evs["HORIZON-2"]["date_type"] == "fuzzy"
        p = (
            c.execute(select(promises).where(promises.c.event_id == evs["SUMMIT"]["event_id"]))
            .mappings()
            .one()
        )
        assert (str(p["guided_start"]), str(p["guided_end"])) == (
            "2027-05-01",
            "2027-08-31",
        )  # tie-break picked A
        assert p["reviewer_kind"] == "model-adjudicated"

    # Outcome document: the extractors disagree on the reserved field -> human queue, not tie-break.
    add_source(
        engine,
        sponsor,
        OUTCOME_HTML,
        source_id="src_2",
        published=datetime(2027, 3, 2, 12, tzinfo=UTC),
        tmp_path=tmp_path,
    )
    n_tb = sum(1 for m, _ in f.calls if m == "tiebreak")
    out2 = run_extraction(engine, execute=True)
    assert out2["queued"] == 1 and sum(1 for m, _ in f.calls if m == "tiebreak") == n_tb
    assert queue_size(engine)["disagreement"] == 1

    (item,) = open_items(engine)
    eid = decide(engine, item, "A", "operator")
    assert eid == evs["HORIZON-2"]["event_id"]
    with engine.connect() as c:
        r = c.execute(select(resolutions).where(resolutions.c.event_id == eid)).mappings().one()
        assert (
            r["outcome_binary"] == 1
            and r["result_category"] == "met"
            and r["primary_source_id"] == "src_2"
        )
        assert r["confirmed_by"] == "human:operator"
        lab = (
            c.execute(
                select(labels).where(labels.c.event_id == eid, labels.c.field == "result_category")
            )
            .mappings()
            .one()
        )
        assert lab["reviewer"] == "human:operator" and lab["reviewer_kind"] == "human"
        assert c.execute(select(review_queue.c.status)).scalar_one() == "closed"


def test_rerun_is_free(engine, sponsor, fake, tmp_path):
    f = fake(answers)
    add_source(
        engine, sponsor, (FIX / "press_release_synthetic.html").read_text(), tmp_path=tmp_path
    )
    run_extraction(engine, execute=True)
    n = len(f.calls)
    # Reset the document and run again: every completion comes from the cache.
    from techbio.core.db import sources

    with engine.begin() as c:
        c.execute(sources.update().values(extract_status="none"))
    out = run_extraction(engine, execute=True)
    assert len(f.calls) == n
    assert out["spend"]["actual_usd"] == 0 and out["spend"]["n_cached"] > 0

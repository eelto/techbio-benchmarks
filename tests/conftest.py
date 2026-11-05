import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="techbio-test-"))
os.environ["TECHBIO_DATA_DIR"] = str(_TMP)
os.environ["TECHBIO_DB_URL"] = f"sqlite:///{_TMP / 'unused.sqlite'}"
os.environ.setdefault("SEC_USER_AGENT", "Test Runner test@example.com")

from techbio.core import config  # noqa: E402
from techbio.core.db import make_engine, metadata, now, sources, sponsors  # noqa: E402
from techbio.core.llm import runner  # noqa: E402
from techbio.core.llm.cache import LLMResponse  # noqa: E402

config.settings.cache_clear()
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine(tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 'ledger.sqlite'}")
    metadata.create_all(e)
    return e


@pytest.fixture
def sponsor(engine):
    with engine.begin() as conn:
        conn.execute(
            sponsors.insert().values(
                sponsor_id="spn_1",
                name="Example Therapeutics, Inc.",
                cik=1,
                tickers=["EXTX"],
                exchange="Nasdaq",
                filer_kind="domestic",
                sic=2834,
                created_recorded_at=now(),
                updated_recorded_at=now(),
            )
        )
    return "spn_1"


def add_source(
    engine,
    sponsor_id,
    text,
    *,
    source_id="src_1",
    type="edgar_8k",
    published=datetime(2026, 10, 1, 13, tzinfo=UTC),
    tmp_path=None,
):
    path = (tmp_path or _TMP) / f"{source_id}.html"
    path.write_text(text)
    with engine.begin() as conn:
        conn.execute(
            sources.insert().values(
                source_id=source_id,
                url=f"https://www.sec.gov/Archives/{source_id}.htm",
                type=type,
                sponsor_id=sponsor_id,
                is_primary=True,
                title="Press release",
                published_at=published,
                retrieved_at=now(),
                sha256=source_id.ljust(64, "0"),
                local_path=str(path),
                content_type="text/html",
                meta={},
                prefilter_status="pending",
                extract_status="none",
                created_recorded_at=now(),
            )
        )
    return source_id


class Fake:
    """Batch + sync provider whose answers depend on (model, source)."""

    def __init__(self, answers):
        self.answers = answers
        self.batches = {}
        self.calls = []

    def _resp(self, key, req, model_key):
        self.calls.append((model_key, req))
        body = self.answers(model_key, req)
        if isinstance(body, Exception):  # the provider answered with an error
            return LLMResponse(key, "", error=f"{type(body).__name__}: {body}")
        if req.schema_name == "catalyst_statements":
            # Answers are checked against the schema; tests written before prompt v2 omit its
            # partner list, which a real provider always returns.
            body.setdefault("partner_mentions", [])
        return LLMResponse(key, json.dumps(body), tokens_in=1000, tokens_out=300)

    def submit(self, items, model):
        bid = f"b{len(self.batches)}"
        self.batches[bid] = [self._resp(k, r, r.model_key) for k, r in items]
        return bid

    def collect(self, bid, keys=None):
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

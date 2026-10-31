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

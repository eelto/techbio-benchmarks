"""Standards enforced on the ledger: provenance (S8), primary-source resolutions (S9), no raw text in
exports (S7), the biosecurity denylist (S6), and slip tracking."""

import csv
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from techbio.core.config import load_yaml
from techbio.core.db import label_sources, labels, now, resolutions
from techbio.ledger.apply import Provenance, Statement, apply_statement
from techbio.ledger.report import write_sample
from techbio.ledger.slip import event_slips

from .conftest import add_source

SECRET_SENTENCE = "Topline data are expected in the first half of 2027 per our internal plan."


def _guidance(text, src, sponsor, conn, d):
    st = Statement(
        kind="guidance",
        event_type="readout",
        asset_name="zorbalimab",
        trial_name="HORIZON-2",
        phase="3",
        timing_text=text,
        quote=SECRET_SENTENCE,
    )
    from techbio.ledger.timing import parse_timing

    st.window_start, st.window_end, st.window_precision = parse_timing(text, d)
    return apply_statement(
        conn, st, Provenance(src, sponsor, d, "auto-agreement:a+b", "auto-agreement")
    )


def test_slips_and_label_provenance(engine, sponsor, tmp_path):
    add_source(engine, sponsor, f"<p>{SECRET_SENTENCE}</p>", source_id="s1", tmp_path=tmp_path)
    add_source(engine, sponsor, "<p>later</p>", source_id="s2", tmp_path=tmp_path)
    add_source(engine, sponsor, "<p>result</p>", source_id="s3", tmp_path=tmp_path)
    with engine.begin() as conn:
        r1 = _guidance("first half of 2027", "s1", sponsor, conn, date(2026, 5, 1))
        r2 = _guidance("second half of 2027", "s2", sponsor, conn, date(2026, 11, 1))
        assert r1.event_id == r2.event_id
        st = Statement(
            kind="outcome",
            event_type="readout",
            asset_name="zorbalimab",
            trial_name="HORIZON-2",
            result_category="met",
            event_date=date(2027, 9, 15),
            quote="x",
        )
        apply_statement(
            conn, st, Provenance("s3", sponsor, date(2027, 9, 15), "human:operator", "human")
        )
        s = event_slips(conn)[r1.event_id]
        assert (s["restatements"], s["slips"], s["slip_days"]) == (2, 1, 184)
        assert s["realized_slip_days"] == (date(2027, 9, 15) - date(2027, 6, 30)).days
        # S8: every label names its reviewer and links to at least one source.
        for lab in conn.execute(select(labels)).mappings():
            assert lab["reviewer"] and lab["reviewer_kind"]
            assert conn.execute(
                select(label_sources).where(label_sources.c.label_id == lab["label_id"])
            ).first()


def test_resolution_requires_primary_source(engine, sponsor):
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(
            resolutions.insert().values(
                event_id="evt_x",
                label_id="lbl_x",
                primary_source_id=None,
                event_date=date(2027, 1, 1),
                result_category="met",
                outcome_binary=1,
                taxonomy_version="v1",
                recorded_at=now(),
            )
        )


def test_exports_no_raw_text(engine, sponsor, tmp_path):
    add_source(engine, sponsor, f"<p>{SECRET_SENTENCE}</p>", source_id="s1", tmp_path=tmp_path)
    with engine.begin() as conn:
        _guidance("first half of 2027", "s1", sponsor, conn, date(2026, 10, 1))
    out = tmp_path / "sample.csv"
    write_sample(engine, out)
    body = out.read_text()
    assert "HORIZON-2" in body or "zorbalimab" in body  # structured facts are there…
    assert SECRET_SENTENCE[:30] not in body  # …source text is not
    cols = next(csv.reader(out.open()))
    assert not {"quote", "passage", "text", "excerpt"} & set(cols)


def test_no_biosecurity():
    deny = {d.lower() for d in load_yaml("benchmarks")["denylist"]}
    assert {"vct", "wmdp", "wmdp-bio", "abc-bench"} <= deny

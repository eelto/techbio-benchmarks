from pathlib import Path

from techbio.ledger import prefilter
from techbio.ledger.quotes import match_quote
from techbio.ledger.sources.fedreg import parse_notice

FIX = Path(__file__).parent / "fixtures"


def test_prefilter_strips_safe_harbor_and_builds_excerpt():
    text = prefilter.html_to_text((FIX / "press_release_synthetic.html").read_bytes())
    res = prefilter.run(text)
    assert res.passed
    assert "HORIZON-2" in res.excerpt and "mid-2027" in res.excerpt
    assert "Private Securities Litigation Reform Act" not in res.excerpt
    assert "Forward-Looking Statements" not in res.excerpt


def test_html_to_text_survives_control_character_entities():
    # EDGAR exhibits exported from Word carry soft line breaks as &#11; (vertical tab), which lxml
    # decodes but refuses to write back into the tree. Seen in 6 real EX-99 releases (2026-10-31).
    raw = (
        b"<html><body><div><p>The Phase 3 SUMMIT trial</p>&#11;topline data are expected"
        b"&#11;in mid-2027.<p>Next paragraph</p>&#12;after a form feed</div></body></html>"
    )
    text = prefilter.html_to_text(raw)
    assert "topline data are expected in mid-2027." in text
    assert "after a form feed" in text
    assert not any(c in text for c in "\x0b\x0c")


def test_prefilter_fails_unrelated_release():
    assert not prefilter.run(
        "Example Therapeutics announces new board member.\n\nShe joins from a bank."
    ).passed


def test_quote_verification_is_verbatim_modulo_whitespace_and_quotes():
    text = "Topline data are expected in the first half of 2027."
    assert match_quote("Topline data are expected in the  first half of 2027", text).accepted
    assert not match_quote("Topline data are expected in H1 2027", text).accepted
    assert not match_quote("short", text).accepted


SYNTHETIC_NOTICE = """
DATES: The meeting will be held on June 4, 2027, from 9 a.m. to 5 p.m. Eastern Time.
SUPPLEMENTARY INFORMATION:
    Agenda: The meeting presentations will be heard, viewed, captioned,
and recorded through an online platform. The Committee will discuss
biologics license application (BLA) 761999, for zorbalimab injection,
submitted by Example Therapeutics, Inc. The proposed indication (use) is
for the treatment of moderate-to-severe atopic dermatitis in adults. FDA
intends to make background material available to the public.
    Procedure: Interested persons may present data.
"""


def test_adcom_notice_parse():
    p = parse_notice(
        SYNTHETIC_NOTICE, "Dermatologic and Ophthalmic Drugs Advisory Committee; Notice of Meeting"
    )
    assert str(p["meeting_date"]) == "2027-06-04"
    assert not p["cancelled"]
    (app,) = p["applications"]
    assert (app["kind"], app["number"], app["drug"]) == ("BLA", "761999", "zorbalimab injection")
    assert app["sponsor"] == "Example Therapeutics, Inc"
    assert app["indication"].startswith("the treatment of moderate")
    assert parse_notice(SYNTHETIC_NOTICE, "X Committee; Notice of Meeting; Cancellation")[
        "cancelled"
    ]

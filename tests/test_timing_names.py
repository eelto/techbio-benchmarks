from datetime import date

import pytest

from techbio.ledger.names import assets_overlap, company_key, indications_conflict, same_company
from techbio.ledger.timing import parse_timing

D = date(2026, 10, 1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("first half of 2027", (date(2027, 1, 1), date(2027, 6, 30), "half")),
        ("1H 2027", (date(2027, 1, 1), date(2027, 6, 30), "half")),
        ("2H27", (date(2027, 7, 1), date(2027, 12, 31), "half")),
        ("1Q 2027", (date(2027, 1, 1), date(2027, 3, 31), "quarter")),
        ("second half of 2027", (date(2027, 7, 1), date(2027, 12, 31), "half")),
        ("Q1 2027", (date(2027, 1, 1), date(2027, 3, 31), "quarter")),
        ("fourth quarter of 2026", (date(2026, 10, 1), date(2026, 12, 31), "quarter")),
        ("mid-2027", (date(2027, 5, 1), date(2027, 8, 31), "range")),
        ("by year-end 2026", (D, date(2026, 12, 31), "range")),
        ("March 15, 2027", (date(2027, 3, 15), date(2027, 3, 15), "day")),
        (
            "PDUFA target action date of March 15, 2027",
            (date(2027, 3, 15), date(2027, 3, 15), "day"),
        ),
        ("2027-06-04", (date(2027, 6, 4), date(2027, 6, 4), "day")),
        ("March 2027", (date(2027, 3, 1), date(2027, 3, 31), "month")),
        ("in 2027", (date(2027, 1, 1), date(2027, 12, 31), "year")),
        ("soon", None),
    ],
)
def test_parse_timing(text, expected):
    assert parse_timing(text, D) == expected


def test_company_matching():
    assert company_key("VERTEX PHARMACEUTICALS INC /MA") == "vertex pharmaceuticals"
    assert same_company("Vertex Pharmaceuticals Incorporated", "VERTEX PHARMACEUTICALS INC /MA")
    assert same_company("Capricor, Inc", "Capricor Therapeutics, Inc.")
    assert same_company("AstraZeneca Pharmaceuticals LP", "AstraZeneca PLC")
    assert not same_company("Vertex Pharmaceuticals", "Vertex Energy Inc")


def test_asset_matching():
    assert assets_overlap(["VX-548"], ["suzetrigine", "VX548"])
    assert assets_overlap(["EXT-101 (zorbalimab)"], ["zorbalimab"])
    assert not assets_overlap(["EXT-101"], ["EXT-202"])


@pytest.mark.parametrize(
    ("a", "b"),
    [
        # Clearly different diseases: another trial of the same drug (pilot run 3, EVO756).
        ("chronic spontaneous urticaria (CSU)", "moderate-to-severe AD patients"),
        ("moderate-to-severe CSU", "migraine prophylaxis"),
        ("lower-risk MDS", "sickle cell disease"),
        ("platinum-resistant ovarian cancer", "pancreatic cancer"),
        ("obesity", "type 2 diabetes"),
        ("AD", "acute myeloid leukemia"),  # 'a…d' is not a spelling of AML
    ],
)
def test_indications_that_conflict(a, b):
    assert indications_conflict(a, b) and indications_conflict(b, a)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("moderate-to-severe CSU", "chronic spontaneous urticaria (CSU)"),
        ("atopic dermatitis", "moderate-to-severe AD patients"),
        ("Dermatitis, Atopic", "AD"),  # CT.gov condition terms are often inverted
        ("lower-risk MDS", "myelodysplastic syndromes"),
        ("PROC", "platinum-resistant ovarian cancer"),
        ("DLB", "dementia with Lewy bodies"),
        ("HFpEF", "heart failure with preserved ejection fraction"),
        ("T2D", "type 2 diabetes"),
        ("early Alzheimer's disease", "Alzheimer's disease"),
        # Too little to tell: never split on these.
        ("advanced solid tumors", "ovarian cancer"),
        (None, "ovarian cancer"),
        ("", "CSU"),
    ],
)
def test_indications_that_may_be_the_same_trial(a, b):
    assert not indications_conflict(a, b) and not indications_conflict(b, a)

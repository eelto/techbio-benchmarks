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
    # CT.gov lead sponsor of Zentalis's DENALI (NCT05128825), dropped by the sweep before
    assert same_company(
        "K-Group, Beta, Inc., a wholly owned subsidiary of Zentalis Pharmaceuticals, Inc",
        "Zentalis Pharmaceuticals, Inc.",
    )
    assert not same_company("K-Group, Beta, Inc.", "Zentalis Pharmaceuticals, Inc.")


# Lead sponsors from the 2026-11-03 CT.gov refresh that the matcher rejected. Each is a wholly owned
# subsidiary, which taxonomy §1 counts as its parent.
MSD = [("Merck Sharp & Dohme", "Merck & Co., Inc.")]


@pytest.mark.parametrize(
    ("lead", "sponsor"),
    [
        ("Kite, A Gilead Company", "GILEAD SCIENCES, INC."),
        ("Karuna Therapeutics, Inc., a Bristol Myers Squibb company", "BRISTOL MYERS SQUIBB CO"),
        ("Juno Therapeutics, Inc., a Bristol-Myers Squibb Company", "BRISTOL MYERS SQUIBB CO"),
        ("Genzyme, a Sanofi Company", "Sanofi"),
        # The subsidiary note itself in parentheses (Morphic, matched before 2026-11-03)
        (
            "Morphic Therapeutic, Inc. (A Wholly Owned Subsidiary of Eli Lilly and Company)",
            "ELI LILLY & Co",
        ),
        ("Dicerna Pharmaceuticals, Inc., a Novo Nordisk company", "NOVO NORDISK A S"),
        # The location in parentheses, whole or cut off by the registry's field length
        (
            "Verona Pharma, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New Jersey USA)",
            "Merck & Co., Inc.",
        ),
        ("Terns, Inc., a subsidiary of Merck & Co., Inc. (Rahway, New ", "Merck & Co., Inc."),
        (
            "Acceleron Pharma, Inc., a wholly-owned subsidiary of Merck & Co., Inc.",
            "Merck & Co., Inc.",
        ),
    ],
)
def test_subsidiaries_named_as_such_match_their_parent(lead, sponsor):
    assert same_company(lead, sponsor)


def test_subsidiaries_named_otherwise_match_only_through_the_alias_list():
    assert not same_company("Merck Sharp & Dohme LLC", "Merck & Co., Inc.")
    assert same_company("Merck Sharp & Dohme LLC", "Merck & Co., Inc.", MSD)
    # Nested: a subsidiary of the subsidiary
    assert same_company(
        "ArQule, Inc., a subsidiary of Merck Sharp & Dohme LLC, a subsidiary of Merck & Co.",
        "Merck & Co., Inc.",
        MSD,
    )
    assert same_company("Merck & Co., Inc.", "Merck Sharp & Dohme LLC", MSD)  # either side


@pytest.mark.parametrize(
    ("lead", "sponsor"),
    [
        # Another company: Merck KGaA is not Merck & Co.; an affiliate is not a subsidiary.
        (
            "Merck Healthcare KGaA, Darmstadt, Germany, an affiliate of Merck KGaA, Darmstadt, Germany",
            "Merck & Co., Inc.",
        ),
        ("Calibr, a division of Scripps Research", "Research Alliance Corp III"),
        ("Foo Bio, a clinical-stage biotechnology company", "Foo Biotechnology Inc."),
        ("COMPASS Pathways", "Compass Therapeutics, Inc."),
    ],
)
def test_other_companies_still_do_not_match(lead, sponsor):
    assert not same_company(lead, sponsor, MSD)


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


def test_the_alias_list_matches_universe_names_and_adds_searches_only_where_needed():
    from techbio.ledger.sources.ctgov import parent_aliases, search_terms

    aliases = parent_aliases()
    for lead, sponsor in [
        ("Merck Sharp & Dohme LLC", "Merck & Co., Inc."),
        ("Janssen Research & Development, LLC", "JOHNSON & JOHNSON"),
        ("Teva Branded Pharmaceutical Products R&D LLC", "TEVA PHARMACEUTICAL INDUSTRIES LTD"),
        ("Bausch Health Americas, Inc.", "Bausch Health Companies Inc."),
    ]:
        assert same_company(lead, sponsor, aliases)
    assert search_terms("JOHNSON & JOHNSON")[1:] == ["Janssen"]
    assert len(search_terms("Merck & Co., Inc.")) == 1  # Merck's own search returns MSD's trials


def test_a_lead_sponsor_that_names_two_universe_companies_is_assigned_to_neither():
    # "QED Therapeutics, a BridgeBio company" reads as both BridgeBio Pharma and the separately
    # listed BridgeBio Oncology Therapeutics (refresh of 2026-11-03).
    from techbio.ledger.sources.ctgov import owner

    universe = [
        ("spn_bbio", "BridgeBio Pharma, Inc."),
        ("spn_bbot", "BridgeBio Oncology Therapeutics, Inc."),
        ("spn_mrk", "Merck & Co., Inc."),
    ]
    assert owner("QED Therapeutics, a BridgeBio company", universe, []) is None
    assert owner("BridgeBio Pharma, Inc.", universe, []) == "spn_bbio"
    assert owner("Merck Sharp & Dohme LLC", universe, MSD) == "spn_mrk"
    assert owner("Merck Sharp & Dohme LLC", universe, []) is None

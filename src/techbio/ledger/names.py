"""Name normalization for matching sponsors (SEC vs CT.gov vs FDA) and assets across documents."""

from __future__ import annotations

import re

_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "plc",
    "llc",
    "lp",
    "sa",
    "ag",
    "nv",
    "se",
    "spa",
    "ab",
    "as",
    "asa",
    "oyj",
    "kk",
    "gmbh",
    "holdings",
    "holding",
    "group",
    "the",
    "adr",
    "ads",
}
_STATE_TAIL = re.compile(r"\s*/\s*[a-z]{2,3}/?\s*$", re.I)
_GENERIC = {
    "therapeutics", "pharmaceuticals", "pharmaceutical", "pharma", "biosciences", "bioscience",
    "biotherapeutics", "biopharma", "biopharmaceuticals", "biotech", "biotechnology", "bio",
    "medicines", "oncology", "sciences", "life", "labs", "laboratories", "and",
}  # "VERTEX PHARMACEUTICALS INC /MA"


def company_key(name: str) -> str:
    """'Vertex Pharmaceuticals Incorporated' and 'VERTEX PHARMACEUTICALS INC /MA' -> 'vertex pharmaceuticals'."""
    s = _STATE_TAIL.sub("", name).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t not in _SUFFIXES]
    while toks and toks[-1] == "and":
        toks.pop()
    return " ".join(toks)


def search_term(name: str) -> str:
    """A short, distinctive query for fuzzy registries (CT.gov): 'Capricor Therapeutics' -> 'capricor'.
    Matches are then confirmed with same_company()."""
    toks = company_key(name).split()
    core = [t for t in toks if t not in _GENERIC] or toks
    return " ".join(toks[:2]) if len(core[0]) < 5 else core[0]


def same_company(a: str, b: str) -> bool:
    ka, kb = company_key(a), company_key(b)
    if not ka or not kb:
        return False
    return (
        ka == kb
        or (len(ka) >= 6 and kb.startswith(ka + " "))
        or (len(kb) >= 6 and ka.startswith(kb + " "))
    )


def asset_key(name: str) -> str:
    """'VX-548 (suzetrigine)' -> 'vx548 suzetrigine'; codes lose dashes and spaces."""
    s = name.lower()
    s = re.sub(r"[®™©]", "", s)
    s = re.sub(r"\b([a-z]{1,5})[-\s]?(\d{2,6}[a-z]?)\b", r"\1\2", s)  # VX-548, ABC 123
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def asset_tokens(names: list[str]) -> set[str]:
    out: set[str] = set()
    for n in names:
        k = asset_key(n)
        if not k:
            continue
        out.add(k)
        out.update(
            t for t in k.split() if len(t) >= 4 and t not in {"placebo", "combination", "therapy"}
        )
    return out


def assets_overlap(a: list[str], b: list[str]) -> bool:
    return bool(asset_tokens(a) & asset_tokens(b))

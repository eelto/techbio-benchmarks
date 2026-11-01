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
    "therapeutics",
    "pharmaceuticals",
    "pharmaceutical",
    "pharma",
    "biosciences",
    "bioscience",
    "biotherapeutics",
    "biopharma",
    "biopharmaceuticals",
    "biotech",
    "biotechnology",
    "bio",
    "medicines",
    "oncology",
    "sciences",
    "life",
    "labs",
    "laboratories",
    "and",
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


_IND_FILLER = {
    *("a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with", "without"),
    *("who", "patient", "patients", "adult", "adults", "subjects", "participants", "people"),
}
# Severity, stage, line of therapy, and nouns every disease shares: overlap on these says nothing
# about whether two indications are one trial.
_IND_GENERIC = {
    *("moderate", "severe", "mild", "chronic", "acute", "early", "late", "stage", "advanced"),
    *("metastatic", "locally", "unresectable", "recurrent", "relapsed", "refractory", "resistant"),
    *("sensitive", "newly", "diagnosed", "previously", "treated", "untreated", "naive", "first"),
    *("second", "third", "line", "high", "low", "lower", "higher", "intermediate", "risk", "grade"),
    *("primary", "secondary", "associated", "related", "induced", "positive", "negative"),
    *("mutant", "mutated", "mutation", "type", "disease", "diseases", "disorder", "disorders"),
    *("syndrome", "syndromes", "cancer", "cancers", "tumor", "tumors", "tumour", "tumours"),
    *("carcinoma", "carcinomas", "neoplasm", "neoplasms", "solid", "cell", "cells", "onset"),
    *("prophylaxis", "prevention", "treatment", "therapy", "maintenance", "adjuvant"),
    *("neoadjuvant", "pediatric", "paediatric", "juvenile"),
}
_ABBREV = re.compile(r"(?=(?:.*[A-Z]){2})[A-Za-z0-9]{2,7}")  # CSU, LR, T2D, HFpEF


def _ind_words(text: str) -> list[str]:
    toks = re.split(r"[^A-Za-z0-9]+", text)  # "Alzheimer's" -> "Alzheimer", "s" (dropped)
    return [t for t in toks if (len(t) > 1 or t.isdigit()) and t.lower() not in _IND_FILLER]


def _content(words: list[str]) -> set[str]:
    out = set()
    for w in (w.lower() for w in words):
        if w in _IND_GENERIC or w.isdigit():
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _spells(short: str, words: list[str], used: int = 0) -> bool:
    """`short` reads off a run of two or more `words` from their start: each word in the run begins
    with the next letter, and later letters may come from inside a word ('MDS' = myelo-d-ysplastic
    syndromes). Stricter than Schwartz & Hearst (2003), which may skip words."""
    if not short:
        return used >= 2
    if not words or not words[0].startswith(short[0]):
        return False
    word, pos = words[0], 1
    for k in range(1, len(short) + 1):
        if _spells(short[k:], words[1:], used + 1):
            return True
        if k == len(short):
            break
        pos = word.find(short[k], pos) + 1
        if not pos:
            break
    return False


def _abbreviates(short: str, words: list[str]) -> bool:
    low = [w.lower() for w in words]
    runs = (seq[i:] for seq in (low, low[::-1]) for i in range(len(seq)))  # "Dermatitis, Atopic"
    return any(_spells(short.lower(), run) for run in runs)


def indications_conflict(a: str | None, b: str | None) -> bool:
    """True only when two indications clearly name different diseases: no disease word in common,
    and neither is an abbreviation of the other. Anything vaguer ("advanced solid tumors", or a
    missing indication) is not a conflict."""
    if not a or not b:
        return False
    wa, wb = _ind_words(a), _ind_words(b)
    ca, cb = _content(wa), _content(wb)
    if not ca or not cb or ca & cb:
        return False
    for short, words in ((s, wb) for s in wa if _ABBREV.fullmatch(s)):
        if _abbreviates(short, words):
            return False
    for short, words in ((s, wa) for s in wb if _ABBREV.fullmatch(s)):
        if _abbreviates(short, words):
            return False
    return True

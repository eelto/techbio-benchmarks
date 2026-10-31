"""Free keyword/regex prefilter, run before any paid call.

It does three things:
- turns a raw document into clean text (HTML -> paragraphs) and drops the safe-harbor boilerplate,
  which mentions trials and approvals in every press release;
- decides pass/fail from catalyst language;
- builds the excerpt the extractors see: paragraphs with hits plus one neighbor each side, capped.

Everything here is deterministic, so the excerpt (and therefore the prompt hash) is stable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import html as lxml_html

BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

PATTERNS: dict[str, list[str]] = {
    "readout": [
        r"top[- ]?line",
        r"primary (?:efficacy )?end ?points?",
        r"met (?:its|the) primary",
        r"did not (?:meet|achieve)",
        r"statistically significant",
        r"pivotal",
        r"registrational",
        r"read[- ]?outs?\b",
        r"phase (?:2b|iib|3|iii|2/3|ii/iii)\b",
    ],
    "fda": [
        r"\bPDUFA\b",
        r"target action date",
        r"complete response letter",
        r"\bCRL\b",
        r"\b(?:s?NDA|s?BLA)\b",
        r"priority review",
        r"accepted (?:for filing|for review)",
        r"(?:FDA|Food and Drug Administration)\W+(?:has\s+)?approv",
        r"marketing application",
    ],
    "adcom": [r"advisory committee", r"\bAdCom\b", r"\bODAC\b", r"\bVRBPAC\b"],
    "discontinuation": [
        r"discontinu",
        r"deprioritiz",
        r"no longer (?:pursue|develop|advance)",
        r"(?:terminat|stopp|halt)(?:e|ed|ing|ion)? (?:the |its |our )?(?:development|program|trial|study)",
        r"return(?:ed)? (?:of )?(?:the )?(?:worldwide )?rights",
        r"futility",
    ],
    "guidance": [
        r"(?:expect|anticipat|plan|on track|guid)\w*.{0,140}?(?:data|results|readout|top[- ]?line|PDUFA|approval|decision|submission)",
        r"\b(?:[12]H|H[12]|first half|second half|mid[- ]|year[- ]end|end of|Q[1-4]|[1-4]Q|(?:first|second|third|fourth) quarter)\W{0,3}(?:of\s)?(?:20)?\d{2}\b",
    ],
}
COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in PATTERNS.items()}
SAFE_HARBOR = re.compile(
    r"^(?:cautionary (?:note|statement)|(?:special note regarding )?forward[- ]looking statements?|safe harbor)\b",
    re.I,
)
SAFE_HARBOR_INLINE = re.compile(
    r"Private Securities Litigation Reform Act|forward-looking statements within the meaning", re.I
)
MAX_EXCERPT_CHARS = 16_000


def html_to_text(raw: bytes) -> str:
    doc = lxml_html.fromstring(raw)
    for bad in doc.xpath("//script|//style|//head"):
        bad.drop_tree()
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.lower() in BLOCK_TAGS:
            el.tail = "\n" + (el.tail or "")
    text = doc.text_content()
    text = text.replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    paras: list[str] = []
    buf: list[str] = []
    for line in lines:
        if not line:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        buf.append(line)
    if buf:
        paras.append(" ".join(buf))
    return "\n\n".join(p for p in paras if p)


def load_text(local_path: str, content_type: str | None) -> str:
    raw = Path(local_path).read_bytes()
    ct = (content_type or "").lower()
    if "json" in ct:
        return raw.decode("utf-8", "replace")
    if "html" in ct or raw.lstrip()[:15].lower().startswith((b"<html", b"<!doctype", b"<document")):
        return html_to_text(raw)
    return raw.decode("utf-8", "replace")


def strip_safe_harbor(paras: list[str]) -> list[str]:
    out: list[str] = []
    for p in paras:
        if len(p) < 120 and SAFE_HARBOR.match(p):
            break  # the safe-harbor section runs to the end of the release
        if SAFE_HARBOR_INLINE.search(p):
            continue
        out.append(p)
    return out


@dataclass
class PrefilterResult:
    passed: bool
    hits: dict[str, int]
    excerpt: str
    full_text: str


def run(text: str) -> PrefilterResult:
    paras = strip_safe_harbor([p for p in text.split("\n\n") if p.strip()])
    full = "\n\n".join(paras)
    hits = {k: 0 for k in COMPILED}
    scored: list[tuple[int, int]] = []
    for i, p in enumerate(paras):
        n = 0
        for k, pats in COMPILED.items():
            c = sum(1 for pat in pats if pat.search(p))
            hits[k] += c
            n += c
        if n:
            scored.append((i, n))
    strong = hits["fda"] + hits["adcom"] + hits["discontinuation"] + hits["readout"]
    passed = strong > 0 and (
        hits["guidance"] > 0
        or hits["readout"] + hits["fda"] + hits["adcom"] >= 2
        or hits["discontinuation"] > 0
    )
    if not passed:
        return PrefilterResult(False, hits, "", full)
    keep: set[int] = set()
    budget = MAX_EXCERPT_CHARS
    for i, _ in sorted(scored, key=lambda t: (-t[1], t[0])):
        for j in (i, i - 1, i + 1):
            if 0 <= j < len(paras) and j not in keep and len(paras[j]) <= budget:
                keep.add(j)
                budget -= len(paras[j])
        if budget <= 0:
            break
    excerpt = "\n\n".join(paras[i] for i in sorted(keep))
    return PrefilterResult(True, hits, excerpt, full)

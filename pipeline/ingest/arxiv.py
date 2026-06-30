"""Layer 1 (alternative) — Formal papers via the arXiv API (spec §5).

Used when OpenAlex is unavailable or rate-limited. OpenAlex now enforces a
~1000-request/day free quota with a paid-credit overage (HTTP 429 +
`Retry-After`), which blocks a large one-shot pull; arXiv has no such daily
quota — its only etiquette is ~1 request / 3 s and <=2000 results per request,
so we page politely.

Pulls are CHUNKED BY YEAR (arXiv `submittedDate` range) for two reasons:
robustness (a stalled year costs one year, not the whole pull) and even
temporal coverage of the evolution map (sorting the whole field by recency
would starve the early slices). Atom XML is parsed with the stdlib — no
feedparser dependency, keeping the synthetic/dev paths dependency-free.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Optional

from ..config import Config
from ..normalize import normalize_arxiv
from ..schema import Record

API = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARX = "{http://arxiv.org/schemas/atom}"
_OS = "{http://a9.com/-/spec/opensearch/1.1/}"

# AI/ML categories where AI-safety work appears (spec §4). The keyword seed
# filter (keywords.py) is the real field boundary, not this list.
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CY", "cs.CR", "stat.ML", "cs.MA"]

# Abstract-targeted safety phrases — the recall net. DISTINCTIVE phrases only:
# bare "alignment"/"interpretability" were removed because arXiv `abs:` matching
# dragged in sequence-alignment / XAI / cognitive-science work that diluted the
# map. Keep roughly aligned with keywords.py NARROW_TERMS.
_CORE = [
    '"AI safety"', '"AI alignment"', '"value alignment"', '"language model alignment"',
    '"mechanistic interpretability"', '"scalable oversight"', '"weak-to-strong"',
    "RLHF", '"reinforcement learning from human feedback"', "RLAIF",
    '"reward hacking"', '"reward model"', '"reward modeling"', '"specification gaming"',
    '"goal misgeneralization"', '"deceptive alignment"', "superalignment",
    "jailbreak", '"red teaming"', '"prompt injection"', '"AI control"',
    '"machine unlearning"', '"existential risk"', '"catastrophic risk"',
    '"sparse autoencoder"', '"constitutional AI"', '"frontier model"',
    '"frontier safety"', "superintelligence", '"dangerous capabilities"',
    "sycophancy", '"situational awareness"', '"preference optimization"',
    '"chain-of-thought monitoring"', '"AGI safety"', '"responsible scaling"',
]
_BROAD_EXTRA = ['"adversarial robustness"', "fairness", '"differential privacy"', "misuse"]


def _term_clause(scope: str) -> str:
    terms = _CORE + (_BROAD_EXTRA if scope == "broad" else [])
    return " OR ".join(f"abs:{t}" for t in terms)


def _query(scope: str, year: int) -> str:
    cats = "(" + " OR ".join(f"cat:{c}" for c in CATEGORIES) + ")"
    return (f"{cats} AND ({_term_clause(scope)}) "
            f"AND submittedDate:[{year}01010000 TO {year}12312359]")


def _request(params: dict, contact: str, attempts: int = 3) -> str:
    """GET with an explicit timeout (the lesson from the OpenAlex hang) and a
    bounded retry on transient failure."""
    import requests

    headers = {"User-Agent": f"ai-safety-thematic-map/0.2 (mailto:{contact or 'anon@example.com'})"}
    last: Optional[Exception] = None
    for i in range(1, attempts + 1):
        try:
            r = requests.get(API, params=params, headers=headers, timeout=40)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001 — bounded; retry then re-raise
            last = e
            time.sleep(3 * i)
    raise last  # type: ignore[misc]


def _parse(xml_text: str) -> tuple[int, list[dict]]:
    root = ET.fromstring(xml_text)
    total_el = root.find(f"{_OS}totalResults")
    total = int(total_el.text) if total_el is not None and total_el.text else 0
    entries: list[dict] = []
    for e in root.findall(f"{_ATOM}entry"):
        def _t(tag: str) -> str:
            el = e.find(f"{_ATOM}{tag}")
            return (el.text or "").strip() if el is not None else ""

        authors = []
        for a in e.findall(f"{_ATOM}author"):
            name_el = a.find(f"{_ATOM}name")
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())
        cats = [c.get("term") for c in e.findall(f"{_ATOM}category") if c.get("term")]
        doi_el = e.find(f"{_ARX}doi")
        entries.append({
            "id": _t("id"), "title": _t("title"), "summary": _t("summary"),
            "published": _t("published"), "authors": authors, "categories": cats,
            "doi": (doi_el.text.strip() if doi_el is not None and doi_el.text else ""),
        })
    return total, entries


def fetch(cfg: Config, since: Optional[str] = None) -> list[Record]:
    """Pull formal records from arXiv, chunked by year. `since` (ISO date) limits
    to years at/after the watermark for incremental refresh (spec §16)."""
    if not cfg.enable_formal:
        return []

    years = list(range(cfg.start_year, cfg.end_year + 1))
    if since:
        ylo = int(since[:4])
        years = [y for y in years if y >= ylo]
    per_year = max(800, cfg.max_formal // max(1, len(years)))
    page = 200
    delay = max(3.0, cfg.request_delay_s)  # arXiv etiquette: >=3 s between calls

    records: dict[str, Record] = {}
    for year in years:
        q = _query(cfg.scope, year)
        got, start = 0, 0
        while got < per_year:
            params = {
                "search_query": q, "start": start, "max_results": page,
                "sortBy": "submittedDate", "sortOrder": "descending",
            }
            try:
                total, entries = _parse(_request(params, cfg.openalex_email))
            except Exception as e:  # noqa: BLE001
                print(f"    arxiv {year}: failed at start={start} "
                      f"({type(e).__name__}: {str(e)[:60]}); stopping year")
                break
            if not entries:
                break
            for ent in entries:
                r = normalize_arxiv(ent, year)
                records[r.doc_id] = r
                got += 1
            start += page
            if start >= total:
                break
            time.sleep(delay)
        print(f"    arxiv {year}: {got} pulled  (running unique: {len(records)})")
        time.sleep(delay)

    return list(records.values())

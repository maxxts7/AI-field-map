"""Layer 1 — Formal papers via OpenAlex (spec §5).

Strategy: combine a topic/keyword search with per-institution (ROR) filters for
the labs in scope. OpenAlex's own keyword fields are AI-derived topic labels,
not author keywords, so we keep them only as `raw_tags` and rely on embedding /
term extraction downstream (spec §9). We use the EARLIEST date to preserve the
leading-edge signal.

pyalex is imported lazily so the rest of the pipeline runs without it.
"""
from __future__ import annotations

from typing import Iterator, Optional

from ..config import Config
from ..keywords import term_list
from ..normalize import normalize_openalex
from ..schema import Record


def _search_clause(scope: str) -> str:
    """A compact OR search string OpenAlex accepts in `search` / filter."""
    # A handful of high-precision phrases; the seed+LLM filter does the rest.
    core = [
        "AI safety", "AI alignment", "scalable oversight", "RLHF",
        "mechanistic interpretability", "reward hacking", "AI control",
        "dangerous capability", "deceptive alignment", "existential risk AI",
    ]
    if scope == "broad":
        core += ["adversarial robustness", "AI fairness", "AI misuse"]
    return " OR ".join(core)


def _install_timeout(seconds: int = 30) -> None:
    """pyalex passes no timeout to requests, so a stalled OpenAlex read hangs
    FOREVER (observed: a 33k single pull blocked 50 min on one dead socket).
    Force a default read/connect timeout on every requests call; pyalex's
    urllib3 Retry then retries the timed-out read, and a truly dead endpoint
    raises (bounded) instead of hanging, so the per-year retry below can recover.
    """
    import requests

    if getattr(requests.Session, "_pyalex_timeout_patched", False):
        return
    _orig = requests.Session.request

    def _patched(self, method, url, **kw):
        kw.setdefault("timeout", seconds)
        return _orig(self, method, url, **kw)

    requests.Session.request = _patched  # type: ignore[method-assign]
    requests.Session._pyalex_timeout_patched = True  # type: ignore[attr-defined]


def _configure(cfg: Config):
    import pyalex

    if cfg.openalex_email:
        pyalex.config.email = cfg.openalex_email
    pyalex.config.max_retries = 3
    pyalex.config.retry_backoff_factor = 0.5
    _install_timeout(30)
    return pyalex


def _years(cfg: Config, since: Optional[str]) -> list[int]:
    lo = int(since[:4]) if since else cfg.start_year
    return list(range(max(cfg.start_year, lo), cfg.end_year + 1))


def fetch(cfg: Config, since: Optional[str] = None) -> list[Record]:
    """Pull formal records, CHUNKED BY YEAR for robustness (a stall costs one
    year, not the whole pull) and for even temporal coverage of the evolution
    map. `since` (ISO date) enables incremental refresh."""
    if not cfg.enable_formal:
        return []
    import time

    pyalex = _configure(cfg)
    from pyalex import Works

    _ = term_list(cfg.scope)  # ensures scope is valid / documented
    years = _years(cfg, since)
    per_year = max(1500, cfg.max_formal // max(1, len(years)))
    clause = _search_clause(cfg.scope)
    records: dict[str, Record] = {}

    for year in years:
        lo = since if (since and int(since[:4]) == year) else f"{year}-01-01"
        q = (
            Works()
            .search_filter(title_and_abstract=clause)
            .filter(from_publication_date=lo)
            .filter(to_publication_date=f"{year}-12-31")
            .filter(type="article")
        )
        got = 0
        for attempt in range(1, 4):
            try:
                got = 0
                for work in _paged(q, per_year):
                    r = normalize_openalex(work, year)
                    records[r.doc_id] = r
                    got += 1
                break
            except Exception as e:  # noqa: BLE001 — bounded; retry the year
                wait = 3 * attempt
                print(f"    {year}: attempt {attempt} failed ({type(e).__name__}: "
                      f"{str(e)[:80]}); retry in {wait}s")
                time.sleep(wait)
        print(f"    {year}: {got} pulled  (running unique: {len(records)})")

    return list(records.values())


def _paged(query, cap: int) -> Iterator[dict]:
    """Cursor-paginate an OpenAlex query up to `cap` results."""
    seen = 0
    for page in query.paginate(per_page=200, n_max=cap):
        for work in page:
            yield work
            seen += 1
            if seen >= cap:
                return

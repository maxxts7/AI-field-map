"""Layer 2 — Lab reports / research blogs (spec §5).

The "non-indexed frontier": output from frontier labs that skews OFF arXiv
(Anthropic interpretability, OpenAI/DeepMind safety posts, transformer-circuits,
Redwood). Highest-effort, lowest-cleanliness layer — each lab exposes its
publications differently, so there is a small per-lab parser registry:

  "feed"                 RSS/Atom via feedparser (DeepMind, OpenAI)
  "year_path"            static bs4 scrape where the year is in the href
                         (transformer-circuits.pub, alignment.anthropic.com)
  "anthropic"            static bs4 scrape ("Category Mon DD, YYYY Title …")
  "cached"               read a pre-captured JSON snapshot for JS-rendered sites
                         (Redwood, Meta FAIR) the static requests path can't see

Etiquette: respect robots.txt, prefer feeds, rate-limit, request timeout.
requests/bs4/feedparser are imported lazily so the synthetic path needs none.
A failing lab leaves a HOLE (logged) rather than guessing (spec §18, §19).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from ..config import Config, LabTarget, PIPELINE_DIR
from ..normalize import normalize_lab
from ..schema import Record

_UA = "ai-safety-thematic-evolution/0.2 (research; contact in repo)"
_CACHE_DIR = PIPELINE_DIR / "data" / "raw" / "labs"

_PARSERS: dict[str, Callable[[LabTarget, Config], list[dict]]] = {}


def register(name: str):
    def deco(fn):
        _PARSERS[name] = fn
        return fn
    return deco


# --- helpers -------------------------------------------------------------
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_TEXTDATE = re.compile(r"([A-Z][a-z]{2})[a-z]*\.?\s+(\d{1,2}),?\s+(20\d\d)")


def _iso_from_textdate(text: str) -> str:
    """'May 8, 2026' / 'Jun 26 2026' -> '2026-05-08'. '' if none found."""
    m = _TEXTDATE.search(text or "")
    if not m:
        return ""
    mon = _MONTHS.get(m.group(1), 0)
    if not mon:
        return ""
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


def _allowed(url: str) -> bool:
    """True unless robots.txt explicitly disallows. Fetched with OUR UA via
    requests — RobotFileParser's own urllib fetch gets Cloudflare-403'd on some
    lab sites and then (per RFC) treats 403 as disallow-all, a false negative.
    Absent/unreachable/4xx robots is treated as allowed (standard convention)."""
    import requests

    try:
        resp = requests.get(urljoin(url, "/robots.txt"),
                            headers={"User-Agent": _UA}, timeout=15)
        if resp.status_code >= 400:
            return True
        rp = RobotFileParser()
        rp.parse(resp.text.splitlines())
        return rp.can_fetch(_UA, url)
    except Exception:  # noqa: BLE001
        return True


def _get(url: str, cfg: Config) -> Optional[str]:
    import requests

    if not _allowed(url):
        print(f"  [labs] robots.txt disallows {url}; skipping")
        return None
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
    resp.raise_for_status()
    time.sleep(cfg.request_delay_s)
    return resp.text


# --- parsers -------------------------------------------------------------
@register("feed")
def _feed(lab: LabTarget, cfg: Config) -> list[dict]:
    """RSS/Atom. feedparser gives `published_parsed` (struct_time) which we turn
    into an ISO date — the raw RFC-822 string would defeat parse_date."""
    import feedparser

    feed = feedparser.parse(lab.feed_url or lab.publications_url)
    items = []
    for e in feed.entries:
        pp = e.get("published_parsed") or e.get("updated_parsed")
        date = time.strftime("%Y-%m-%d", pp) if pp else (e.get("published", "")[:10])
        items.append({
            "title": e.get("title", ""),
            "summary": re.sub(r"<[^>]+>", " ", e.get("summary", "")),
            "url": e.get("link", ""),
            "date": date,
            "authors": [a.get("name", "") for a in e.get("authors", []) if a.get("name")],
            "lab": lab.name,
        })
    return items


@register("year_path")
def _year_path(lab: LabTarget, cfg: Config) -> list[dict]:
    """Distill-style index where each post is `<a href='20YY/slug/…'>Title …`."""
    from bs4 import BeautifulSoup

    html = _get(lab.publications_url, cfg)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        ym = re.match(r"(20\d\d)/", href)  # year lives in the relative path
        text = a.get_text(" ", strip=True)
        if not ym or len(text) < 12:
            continue
        items.append({
            "title": text[:140],
            "summary": text[140:600],
            "url": urljoin(lab.publications_url, href),
            "date": ym.group(1),  # year-only -> parse_date mid-years it
            "lab": lab.name,
        })
    return items


@register("anthropic")
def _anthropic(lab: LabTarget, cfg: Config) -> list[dict]:
    from bs4 import BeautifulSoup

    html = _get(lab.publications_url, cfg)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        date = _iso_from_textdate(text)
        if len(text) < 20 or not date:
            continue  # research entries carry a date; nav/footer links don't
        # strip the "Mon DD, YYYY" off the title (category prefix is left as-is)
        title = _TEXTDATE.sub("", text, count=1).strip(" -—|")
        items.append({
            "title": title[:140], "summary": text[:600],
            "url": urljoin(lab.publications_url, a["href"]),
            "date": date, "lab": lab.name,
        })
    return items


@register("cached")
def _cached(lab: LabTarget, cfg: Config) -> list[dict]:
    """Read a JSON snapshot captured out-of-band for a JS-rendered site whose
    publication list the static path can't see. Missing file -> empty (a hole)."""
    key = _source_name(lab)
    path = _CACHE_DIR / f"{key}.json"
    if not path.exists():
        print(f"  [labs] no cached snapshot for {lab.name} at {path}; leaving a hole")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    for it in data:
        it.setdefault("lab", lab.name)
    return data


def _source_name(lab: LabTarget) -> str:
    url = lab.publications_url or lab.feed_url
    return url.split("/")[2] if "//" in url else lab.name


def fetch(cfg: Config, since: Optional[str] = None) -> list[Record]:
    if not cfg.enable_lab_report:
        return []
    out: dict[str, Record] = {}
    for lab in cfg.labs:
        extract = _PARSERS.get(lab.parser)
        if not extract:
            print(f"  [labs] {lab.name}: no parser '{lab.parser}'; skipping")
            continue
        source_name = _source_name(lab)
        try:
            items = extract(lab, cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  [labs] {lab.name} failed ({type(exc).__name__}: {exc}); leaving a hole")
            continue
        kept = 0
        for item in items:
            r = normalize_lab(item, source_name)
            r.curated = lab.curated
            if since and r.date < since:
                continue
            out.setdefault(r.doc_id, r)
            kept += 1
        print(f"  [labs] {lab.name}: {kept} items ({lab.parser})")
    return list(out.values())

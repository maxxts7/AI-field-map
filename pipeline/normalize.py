"""Normalisation: raw source payloads -> the unified Record schema (spec §6).

Each source has its own quirks (OpenAlex's inverted-index abstracts, ForumMagnum
HTML bodies, scraped listings); they are reconciled here so the rest of the
pipeline is source-agnostic.
"""
from __future__ import annotations

import re
from typing import Any

from .schema import Record, make_doc_id, parse_date

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _reconstruct_abstract(inv: dict[str, list[int]] | None) -> str:
    """OpenAlex ships abstracts as an inverted index (term -> positions)."""
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def normalize_openalex(work: dict[str, Any], fallback_year: int) -> Record:
    title = work.get("title") or work.get("display_name") or ""
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))
    authorships = work.get("authorships", []) or []
    authors = [a.get("author", {}).get("display_name", "") for a in authorships]
    affils: list[str] = []
    for a in authorships:
        for inst in a.get("institutions", []) or []:
            if inst.get("display_name"):
                affils.append(inst["display_name"])

    # earliest date preserves the leading-edge signal (spec §5)
    raw_date = work.get("publication_date") or (
        f"{work.get('publication_year')}" if work.get("publication_year") else None
    )
    arxiv_id = ""
    for loc in work.get("locations", []) or []:
        url = (loc.get("landing_page_url") or "") + (loc.get("pdf_url") or "")
        m = _ARXIV_RE.search(url)
        if m:
            arxiv_id = m.group(1)
            break

    topics = [t.get("display_name", "") for t in work.get("topics", []) or []]
    oa_id = work.get("id", "")

    return Record(
        doc_id=make_doc_id("openalex", oa_id),
        source_layer="formal",
        source_name="openalex",
        title=title,
        body_text=abstract,
        date=parse_date(raw_date, fallback_year),
        url=oa_id,
        doi=(work.get("doi") or "").replace("https://doi.org/", ""),
        arxiv_id=arxiv_id,
        authors=[a for a in authors if a],
        affiliations=sorted(set(affils)),
        raw_tags=[t for t in topics if t],
        citation_count=work.get("cited_by_count"),
    )


_ARXIV_ID_RE = re.compile(r"abs/([a-z\-]+/\d+|\d{4}\.\d{4,5})", re.I)


def normalize_arxiv(entry: dict[str, Any], fallback_year: int) -> Record:
    """One parsed arXiv Atom <entry> dict -> Record (spec §6). arXiv is a formal
    source but ships no citation count, so that field stays None."""
    raw_id = entry.get("id", "") or ""
    m = _ARXIV_ID_RE.search(raw_id)
    arxiv_id = m.group(1) if m else raw_id.rsplit("/", 1)[-1].split("v")[0]
    title = re.sub(r"\s+", " ", entry.get("title", "") or "").strip()
    summary = re.sub(r"\s+", " ", entry.get("summary", "") or "").strip()
    cats = [c for c in (entry.get("categories") or []) if c]
    return Record(
        doc_id=make_doc_id("arxiv", arxiv_id or raw_id),
        source_layer="formal",
        source_name="arxiv",
        title=title,
        body_text=summary,
        date=parse_date(entry.get("published"), fallback_year),
        url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else raw_id,
        doi=(entry.get("doi") or "").replace("https://doi.org/", ""),
        arxiv_id=arxiv_id,
        authors=[a for a in (entry.get("authors") or []) if a],
        raw_tags=cats,
        citation_count=None,
    )


def normalize_forum(post: dict[str, Any], source_name: str = "alignmentforum") -> Record:
    title = post.get("title") or ""
    body = _strip_html(post.get("contents", {}).get("html", "") if isinstance(post.get("contents"), dict) else post.get("htmlBody", ""))
    tags = [t.get("name", "") for t in (post.get("tags") or [])]
    user = (post.get("user") or {}).get("displayName") or post.get("author") or ""
    return Record(
        doc_id=make_doc_id(source_name, post.get("_id") or post.get("pageUrl") or title),
        source_layer="forum",
        source_name=source_name,
        title=title,
        body_text=body,
        date=parse_date(post.get("postedAt"), 2016),
        url=post.get("pageUrl") or post.get("url") or "",
        authors=[user] if user else [],
        raw_tags=[t for t in tags if t],
    )


def normalize_lab(item: dict[str, Any], source_name: str) -> Record:
    title = item.get("title") or ""
    summary = _strip_html(item.get("summary") or item.get("abstract") or "")
    url = item.get("url") or item.get("link") or ""
    m = _ARXIV_RE.search(url + " " + (item.get("arxiv") or ""))
    return Record(
        doc_id=make_doc_id(source_name, url or title),
        source_layer="lab_report",
        source_name=source_name,
        title=title,
        body_text=summary,
        date=parse_date(item.get("date"), 2016),
        url=url,
        arxiv_id=m.group(1) if m else (item.get("arxiv_id") or ""),
        authors=item.get("authors") or [],
        affiliations=[item.get("lab")] if item.get("lab") else [],
        raw_tags=item.get("tags") or [],
    )

"""Deduplication (spec §8). One idea may appear across layers (forum post ->
preprint -> conference paper -> lab summary = four records).

Two passes:
  - Within-layer: DOI / arXiv-id hard match, else fuzzy title+author.
  - Cross-layer: fuzzy title similarity; arXiv id is a hard key when captured.

On merge: keep the EARLIEST date and RETAIN ALL source layers — a record can be
both `formal` and `forum`; layer tags are never discarded (spec §8, §12).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .schema import Record

_NORM = re.compile(r"[^a-z0-9]+")


def _norm_title(t: str) -> str:
    return _NORM.sub(" ", (t or "").lower()).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _merge_into(keep: Record, other: Record) -> None:
    # earliest date wins
    if other.date < keep.date:
        keep.date = other.date
    # retain all layers
    keep.source_layers = sorted(set(keep.source_layers) | set(other.source_layers))
    # backfill hard keys / richer fields
    keep.arxiv_id = keep.arxiv_id or other.arxiv_id
    keep.doi = keep.doi or other.doi
    keep.url = keep.url or other.url
    if not keep.body_text or len(other.body_text) > len(keep.body_text):
        keep.body_text = keep.body_text or other.body_text
    keep.authors = keep.authors or other.authors
    keep.affiliations = sorted(set(keep.affiliations) | set(other.affiliations))
    keep.raw_tags = sorted(set(keep.raw_tags) | set(other.raw_tags))
    if other.citation_count is not None:
        keep.citation_count = max(keep.citation_count or 0, other.citation_count)


def deduplicate(records: list[Record], title_threshold: float = 0.9) -> list[Record]:
    # Pass A — hard keys (arXiv id, then DOI). Cheap and exact.
    by_hard: dict[str, Record] = {}
    leftover: list[Record] = []
    for r in records:
        key = (r.arxiv_id and f"arxiv:{r.arxiv_id}") or (r.doi and f"doi:{r.doi}")
        if key:
            if key in by_hard:
                _merge_into(by_hard[key], r)
            else:
                by_hard[key] = r
        else:
            leftover.append(r)

    merged = list(by_hard.values()) + leftover

    # Pass B — fuzzy title (within + cross layer). Bucket by a coarse prefix to
    # keep this near-linear instead of O(n^2) over the whole corpus.
    buckets: dict[str, list[Record]] = {}
    for r in merged:
        nt = _norm_title(r.title)
        buckets.setdefault(nt[:8], []).append(r)

    out: list[Record] = []
    for group in buckets.values():
        kept: list[Record] = []
        for r in group:
            nt = _norm_title(r.title)
            match = next(
                (k for k in kept if _similar(_norm_title(k.title), nt) >= title_threshold),
                None,
            )
            if match:
                _merge_into(match, r)
            else:
                kept.append(r)
        out.extend(kept)
    return out

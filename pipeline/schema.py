"""The unified record schema (spec §6). Every record from every layer
normalises to this one shape before it enters the working store."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

SourceLayer = Literal["formal", "lab_report", "forum"]


@dataclass
class Record:
    doc_id: str
    source_layer: SourceLayer  # mandatory — never blended without it (spec §12)
    source_name: str  # e.g. "openalex", "anthropic.com", "alignmentforum"
    title: str
    body_text: str  # abstract (formal/lab) or post body (forum)
    date: str  # ISO yyyy-mm-dd; EARLIEST date (spec §5)
    url: str = ""
    doi: str = ""
    arxiv_id: str = ""  # hard key for cross-layer dedup (spec §8)
    authors: list[str] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    raw_tags: list[str] = field(default_factory=list)
    citation_count: Optional[int] = None  # formal layer only, optional
    # filled later in the pipeline:
    embedding: Optional[list[float]] = None  # §9
    topic_id: Optional[int] = None  # §11
    safety_relevant: Optional[bool] = None  # §7
    # provenance: kept alongside raw + normalized copies (spec §6)
    source_layers: list[str] = field(default_factory=list)  # all layers on merge
    # curated source (e.g. transformer-circuits, Redwood, Alignment Forum) whose
    # venue already implies topicality -> admitted without a keyword hit (§7).
    curated: bool = False

    def __post_init__(self) -> None:
        if not self.source_layers:
            self.source_layers = [self.source_layer]

    @property
    def year(self) -> int:
        return int(self.date[:4])

    @property
    def text(self) -> str:
        """The text fed to embedding / term extraction."""
        return f"{self.title}. {self.body_text}".strip()


def make_doc_id(source_name: str, key: str) -> str:
    """Stable id from a source-native key so re-pulls are idempotent."""
    h = hashlib.sha1(f"{source_name}:{key}".encode("utf-8")).hexdigest()[:16]
    return f"{source_name.split('.')[0]}-{h}"


def parse_date(value: str | None, fallback_year: int) -> str:
    """Best-effort ISO date; falls back to mid-year for year-only sources."""
    if not value:
        return f"{fallback_year}-07-01"
    value = value.strip()
    for fmt_len in (10, 7, 4):
        if len(value) < fmt_len:
            continue  # don't let "2025" fall into the 7-char (YYYY-MM) branch
        chunk = value[:fmt_len]
        try:
            if fmt_len == 10:
                date.fromisoformat(chunk)
                return chunk
            if fmt_len == 7:
                date.fromisoformat(f"{chunk}-01")
                return f"{chunk}-01"
            if fmt_len == 4:
                int(chunk)
                return f"{chunk}-07-01"
        except ValueError:
            continue
    return f"{fallback_year}-07-01"

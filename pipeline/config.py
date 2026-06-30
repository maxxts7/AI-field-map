"""Central, load-bearing configuration for the offline compute tier (Tier A).

Everything that shapes the map and must be reproducible (spec §16, §19) lives
here: the field boundary scope, the lab list, time range, slice width, model
names, and random seed. Override any of these via environment variables or the
CLI flags in run.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

# --- paths ---------------------------------------------------------------
PIPELINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PIPELINE_DIR.parent
PUBLIC_DATA = REPO_ROOT / "public" / "data"
RAW_DIR = PIPELINE_DIR / "data" / "raw"
CACHE_DIR = PIPELINE_DIR / ".cache"
DB_PATH = PIPELINE_DIR / "corpus.db"

Scope = Literal["narrow", "broad"]
SliceWidth = Literal["annual", "biannual"]


@dataclass
class LabTarget:
    """One organisation in scope: a ROR id for Layer 1 affiliation filtering
    and a Layer 2 source (spec §5).

    `parser` selects how Layer 2 ingests it (labs.py registry):
      "feed"   — RSS/Atom via feedparser (use `feed_url`)
      a site key ("transformer_circuits", "anthropic") — static bs4 scrape
      "cached" — read a pre-captured JSON snapshot (JS-rendered sites whose
                 publication list the static `requests` path can't see; the
                 snapshot is captured out-of-band and cached for reproducibility)
    `curated` marks all-safety venues admitted without a keyword hit (spec §7)."""

    name: str
    ror: str  # ROR id (look up on ror.org); affiliation filter for OpenAlex
    publications_url: str = ""  # Layer 2 scrape target (optional)
    parser: str = "html_listing"
    feed_url: str = ""
    curated: bool = False


# ROR ids verified on ror.org. Affiliation coverage is uneven by lab (spec §5):
# DeepMind / Meta FAIR are well captured on arXiv; OpenAI / Anthropic skew
# non-arXiv, so Layer 1 under-counts them and Layer 2 compensates.
DEFAULT_LABS: list[LabTarget] = [
    # Clean live sources (feed / static HTML the requests path CAN see).
    LabTarget("Google DeepMind", "00971b820", "https://deepmind.google/blog",
              parser="feed", feed_url="https://deepmind.google/blog/rss.xml"),
    LabTarget("OpenAI", "05wx9n238", "https://openai.com/news/",
              parser="feed", feed_url="https://openai.com/news/rss.xml"),
    LabTarget("Anthropic", "00t0gp064", "https://www.anthropic.com/research",
              parser="anthropic"),
    LabTarget("Anthropic Alignment", "", "https://alignment.anthropic.com/",
              parser="year_path", curated=True),
    LabTarget("transformer-circuits.pub", "", "https://transformer-circuits.pub/",
              parser="year_path", curated=True),
    # JS-rendered sources the static path can't see -> cached browser snapshot.
    LabTarget("Redwood Research", "", "https://www.redwoodresearch.org/research",
              parser="cached", curated=True),
    LabTarget("Meta (FAIR)", "01u8s3r70", "https://ai.meta.com/research/publications/",
              parser="cached"),
]

# Forum endpoints share the open-source ForumMagnum codebase (spec §5).
ALIGNMENT_FORUM_GRAPHQL = "https://www.alignmentforum.org/graphql"
LESSWRONG_GRAPHQL = "https://www.lesswrong.com/graphql"


@dataclass
class Config:
    # --- field boundary (spec §4, §7) ---
    scope: Scope = "narrow"  # narrow: alignment/interp/oversight/x-risk
    #                          broad: also fairness/robustness/misuse
    # --- time / slicing (spec §10) ---
    start_year: int = 2016
    end_year: int = 2026
    slice_width: SliceWidth = "annual"
    # --- layers (spec §4) ---
    # Formal-layer (Layer 1) source: "openalex" (default) or "arxiv". arXiv is
    # the fallback when OpenAlex hits its daily request quota (HTTP 429); set via
    # FORMAL_SOURCE env or run.py --formal-source.
    formal_source: str = os.environ.get("FORMAL_SOURCE", "openalex")
    enable_formal: bool = True
    enable_lab_report: bool = True
    enable_forum: bool = True
    labs: list[LabTarget] = field(default_factory=lambda: list(DEFAULT_LABS))
    # --- embedding / topics (spec §9, §11) ---
    embedding_model: str = "all-MiniLM-L6-v2"
    min_topic_size: int = 12
    seed: int = 42
    # --- classifier (spec §7) ---
    use_llm_classifier: bool = bool(os.environ.get("ANTHROPIC_API_KEY"))
    llm_model: str = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
    classifier_version: str = "boundary-v1"
    # --- field boundary precision (spec §7 stage 1) ---
    # Distinct keyword hits a FORMAL paper needs to pass the seed filter. 1 =
    # high recall (default); 2 = sharper boundary (drops papers that only
    # incidentally touch one safety term). Set via MIN_FORMAL_HITS env.
    min_formal_seed_hits: int = int(os.environ.get("MIN_FORMAL_HITS", "1"))
    # --- ingestion etiquette (spec §5) ---
    openalex_email: str = os.environ.get("OPENALEX_EMAIL", "")
    request_delay_s: float = 1.0
    # --- caps (keep MVP small; raise for full runs) ---
    max_formal: int = 6000
    max_forum: int = 4000

    @property
    def slices(self) -> list[str]:
        """Ordered slice labels, left-to-right on the Sankey."""
        if self.slice_width == "annual":
            return [str(y) for y in range(self.start_year, self.end_year + 1)]
        out: list[str] = []
        for y in range(self.start_year, self.end_year + 1, 2):
            hi = min(y + 1, self.end_year)
            out.append(f"{y}" if hi == y else f"{y}-{hi}")
        return out

    def slice_for_year(self, year: int) -> str | None:
        year = max(self.start_year, min(self.end_year, year))
        if self.slice_width == "annual":
            return str(year)
        base = self.start_year + ((year - self.start_year) // 2) * 2
        hi = min(base + 1, self.end_year)
        return f"{base}" if hi == base else f"{base}-{hi}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["labs"] = [asdict(l) for l in self.labs]
        return d


def load() -> Config:
    """Build a Config, applying a few env overrides if present."""
    cfg = Config()
    if os.environ.get("SCOPE") in ("narrow", "broad"):
        cfg.scope = os.environ["SCOPE"]  # type: ignore[assignment]
    if os.environ.get("START_YEAR"):
        cfg.start_year = int(os.environ["START_YEAR"])
    if os.environ.get("END_YEAR"):
        cfg.end_year = int(os.environ["END_YEAR"])
    if os.environ.get("MAX_FORMAL"):
        cfg.max_formal = int(os.environ["MAX_FORMAL"])
    if os.environ.get("MAX_FORUM"):
        cfg.max_forum = int(os.environ["MAX_FORUM"])
    return cfg

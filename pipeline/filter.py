"""Corpus filtering — the field boundary (spec §7), the single largest source
of methodological risk (spec §4).

Two stages:
  1. Keyword seed filter (HIGH RECALL) — keywords.py.
  2. LLM classifier pass (PRECISION) — judges whether a document's *core
     contribution* is AI safety vs adjacent ethics/fairness/general ML.

The classifier prompt + model + version are part of the experiment and are
stored (spec §7, §16). Results cache per doc_id so re-runs only classify new
documents. With no ANTHROPIC_API_KEY the pipeline runs keyword-only and says so.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Optional

from .config import Config
from .keywords import build_matcher, keyword_hits
from .schema import Record

# Stored verbatim so the boundary is reproducible.
CLASSIFIER_SYSTEM = (
    "You are screening research documents for a science map of the AI SAFETY "
    "field. Decide whether the document's CORE contribution is technical AI "
    "safety/alignment (e.g. alignment, scalable oversight, interpretability, "
    "AI control, evaluations of dangerous capabilities, existential/catastrophic "
    "risk from AI). Documents whose core contribution is general ML, NLP "
    "capabilities, or adjacent ethics/fairness WITHOUT a safety-critical framing "
    "are NOT in scope (unless the run uses the 'broad' scope). Answer strictly as "
    'JSON: {"relevant": true|false, "reason": "<= 15 words"}.'
)


@dataclass
class FilterStats:
    identified: int = 0
    seed_passed: int = 0
    classified: int = 0
    included: int = 0

    def prisma(self) -> dict:
        """PRISMA-style flow record (spec §7)."""
        return {
            "identification": self.identified,
            "screening_seed_passed": self.seed_passed,
            "eligibility_classified": self.classified,
            "included": self.included,
        }


def seed_filter(records: list[Record], cfg: Config) -> tuple[list[Record], list[Record]]:
    """Stage 1. Returns (candidates, rejected). Forum/lab records are admitted
    leniently (their venue already implies topicality); formal needs a hit."""
    matcher = build_matcher(cfg.scope)
    need = max(1, cfg.min_formal_seed_hits)
    candidates, rejected = [], []
    for r in records:
        hits = keyword_hits(r.text, matcher)
        # Admission (spec §7 stage 1):
        #  - forum + CURATED lab sources (transformer-circuits, Redwood, AF):
        #    venue implies topicality -> admit leniently.
        #  - general lab feeds (DeepMind blog, OpenAI news): NOT all safety, so
        #    require >=1 keyword hit, else product/company news floods the map.
        #  - formal papers: need `need` DISTINCT safety-term hits.
        lenient = r.source_layer == "forum" or (r.source_layer == "lab_report" and r.curated)
        if lenient or (r.source_layer == "lab_report" and hits) or len(hits) >= need:
            r.raw_tags = sorted(set(r.raw_tags) | set(hits))
            candidates.append(r)
        else:
            rejected.append(r)
    return candidates, rejected


def _classify_one(client, model: str, rec: Record) -> tuple[bool, str]:
    text = rec.text[:6000]
    msg = client.messages.create(
        model=model,
        max_tokens=80,
        system=CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": f"TITLE: {rec.title}\n\nTEXT: {text}"}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(raw[raw.find("{") : raw.rfind("}") + 1])
        return bool(data.get("relevant")), str(data.get("reason", ""))[:120]
    except Exception:  # noqa: BLE001 — be conservative on parse failure
        return True, "unparsed; kept"


def llm_classify(
    candidates: list[Record],
    cfg: Config,
    get_cached: Optional[Callable[[str], Optional[bool]]] = None,
    set_cached: Optional[Callable[[str, bool, str], None]] = None,
) -> FilterStats:
    """Stage 2. Sets `safety_relevant` on each candidate. Cached per doc_id."""
    stats = FilterStats(identified=len(candidates), seed_passed=len(candidates))

    if not cfg.use_llm_classifier:
        # Keyword-only mode: seed hits stand in for relevance.
        for r in candidates:
            r.safety_relevant = True
        stats.classified = 0
        stats.included = len(candidates)
        return stats

    import anthropic  # lazy

    client = anthropic.Anthropic()
    for r in candidates:
        cached = get_cached(r.doc_id) if get_cached else None
        if cached is not None:
            r.safety_relevant = cached
            continue
        relevant, reason = _classify_one(client, cfg.llm_model, r)
        r.safety_relevant = relevant
        stats.classified += 1
        if set_cached:
            set_cached(r.doc_id, relevant, reason)

    stats.included = sum(1 for r in candidates if r.safety_relevant)
    return stats


def included(records: list[Record]) -> list[Record]:
    return [r for r in records if r.safety_relevant]

"""The AI-safety keyword seed (spec §7, stage 1: high-recall filter).

A curated term list applied to titles/bodies to produce a candidate set, which
the LLM classifier then refines for precision. The `narrow` scope is the core
technical-safety field; `broad` additionally admits fairness / robustness /
misuse. Switching scope changes the entire map and MUST be documented (spec §4).
"""
from __future__ import annotations

import re

# Core technical AI-safety terms (the "narrow" boundary). Seeded from the
# published ~114-term safety list in prior work and extended.
NARROW_TERMS: list[str] = [
    "ai safety", "ai alignment", "value alignment", "aligned ai",
    "alignment research", "misalignment", "outer alignment", "inner alignment",
    "reward hacking", "reward modeling", "reward model", "specification gaming",
    "goal misgeneralization", "deceptive alignment", "mesa-optimization",
    "mesa optimizer", "scalable oversight", "ai oversight", "weak-to-strong",
    "rlhf", "reinforcement learning from human feedback", "rlaif",
    "constitutional ai", "preference learning", "preference modeling",
    "debate", "ai debate", "recursive reward modeling", "iterated amplification",
    "interpretability", "mechanistic interpretability", "circuit analysis",
    "feature visualization", "sparse autoencoder", "dictionary learning",
    "activation patching", "probing classifier", "representation engineering",
    "superposition", "polysemanticity", "induction head", "grokking",
    "ai control", "ai governance", "model evaluation", "dangerous capability",
    "capability evaluation", "red teaming", "red-teaming", "jailbreak",
    "adversarial prompt", "prompt injection", "model autonomy",
    "situational awareness", "power-seeking", "instrumental convergence",
    "corrigibility", "shutdown problem", "tripwire", "honeypot",
    "existential risk", "catastrophic risk", "x-risk", "agi safety",
    "superintelligence", "transformative ai", "loss of control", "takeover",
    "ai risk", "frontier model", "frontier ai", "dangerous capabilities",
    "unlearning", "machine unlearning", "model editing", "knowledge editing",
    "truthfulness", "hallucination", "faithfulness", "sycophancy",
    "calibration", "uncertainty estimation", "selective prediction",
    "anomaly detection", "out-of-distribution", "ood detection",
    "trojan", "backdoor attack", "data poisoning", "model stealing",
    "watermarking", "provenance", "tamper resistance", "guardrails",
    "refusal", "safety fine-tuning", "harmlessness", "helpfulness",
    "content moderation", "toxicity", "alignment tax", "reward tampering",
    "goal-directedness", "agent foundations", "embedded agency",
    "decision theory", "cooperative ai", "multi-agent safety",
    "chain-of-thought monitoring", "process supervision", "scalable alignment",
    "eval awareness", "sandbagging", "model organisms", "sleeper agent",
    "emergent capability", "evaluations", "frontier safety", "responsible scaling",
]

# High-recall ANCHOR terms (spec §4, §7 stage 1). These are common, plainer
# words ("alignment", "interpretability", "oversight") that genuine AI-safety
# papers use without ever spelling out a precise bigram like "AI alignment".
# They are deliberately broad and are safe ONLY because the candidate pool is
# already constrained upstream to AI-safety topics by the OpenAlex targeted
# search (ingest/openalex.py::_search_clause). Adding them roughly DOUBLES seed
# recall (~18% -> ~38% on a relevance-sorted sample), which is what lets the
# corpus reach ~10k papers. This is a documented widening of the narrow field
# boundary — drop this list to return to the strict high-precision boundary.
NARROW_ANCHOR_TERMS: list[str] = [
    "alignment", "aligned", "misaligned", "superalignment", "alignment faking",
    "safety", "ai safety evaluation", "safe reinforcement", "safe rl",
    "interpretability", "interpretable", "oversight",
    "jailbreaking", "red team", "red-team", "scheming", "deceptive",
    "guardrail", "harmful", "adversarial example", "watermark", "backdoor",
    "agentic", "autonomy", "catastrophic", "existential", "evaluation",
]

# Additional terms admitted only under the "broad" scope.
BROAD_EXTRA_TERMS: list[str] = [
    "fairness", "algorithmic bias", "discrimination", "demographic parity",
    "equalized odds", "robustness", "adversarial robustness", "distribution shift",
    "certified robustness", "privacy", "differential privacy", "membership inference",
    "misuse", "dual-use", "disinformation", "deepfake", "misinformation",
    "bias mitigation", "explainability", "accountability", "transparency",
    "ai ethics", "responsible ai", "trustworthy ai",
]


def term_list(scope: str) -> list[str]:
    # NARROW_ANCHOR_TERMS widen seed recall to reach a ~10k corpus (see note
    # above); they apply to both scopes since the OpenAlex query is the real
    # topical gate. Drop them to restore the strict high-precision boundary.
    terms = list(NARROW_TERMS) + list(NARROW_ANCHOR_TERMS)
    if scope == "broad":
        terms += BROAD_EXTRA_TERMS
    return terms


def build_matcher(scope: str) -> re.Pattern:
    """One compiled alternation of word-boundary-anchored phrases."""
    terms = sorted(term_list(scope), key=len, reverse=True)
    escaped = [re.escape(t).replace(r"\ ", r"\s+") for t in terms]
    return re.compile(r"(?<![\w-])(" + "|".join(escaped) + r")(?![\w-])", re.I)


def keyword_hits(text: str, matcher: re.Pattern) -> list[str]:
    return sorted({m.group(1).lower() for m in matcher.finditer(text or "")})


def passes_seed_filter(text: str, matcher: re.Pattern, min_hits: int = 1) -> bool:
    """High recall: a single seed hit admits the candidate (spec §7 stage 1)."""
    return len(keyword_hits(text, matcher)) >= min_hits

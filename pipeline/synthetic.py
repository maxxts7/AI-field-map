"""Synthetic artifact generator — NOT part of the real pipeline.

Produces realistic-looking aggregates (the same JSON shapes export.py writes)
using only the standard library, so the front end renders end-to-end with no
network, API keys, or ML dependencies. The storyline encodes known AI-safety
field history (spec §18 face validity): interpretability sharpening into
mechanistic interpretability, sparse autoencoders splitting off, RLHF spawning
constitutional AI, agent-foundations declining and dying, evaluations / control
emerging recently. Replace with a real `run.py` run for live data.
"""
from __future__ import annotations

import random
from typing import Optional

from .config import Config

# Each lineage is one theme line. (key, start, end, size_start, size_end,
# label-breakpoints, quadrant-breakpoints, (formal,lab,forum) mix, terms)
LINEAGES = [
    ("reward-modeling", 2016, 2019, 6, 16,
     [(2016, "reward modeling")], [(2016, "emerging"), (2018, "niche")],
     (0.60, 0.15, 0.25),
     ["reward modeling", "reward function", "inverse rl", "preferences", "value"]),
    ("value-learning", 2016, 2018, 6, 11,
     [(2016, "value learning")], [(2016, "emerging")],
     (0.45, 0.10, 0.45),
     ["value learning", "human values", "preferences", "utility", "corrigibility"]),
    ("agent-foundations", 2016, 2021, 11, 7,
     [(2016, "agent foundations"), (2019, "embedded agency")],
     [(2016, "niche"), (2020, "emerging")],
     (0.10, 0.05, 0.85),
     ["agent foundations", "embedded agency", "decision theory", "logical induction", "corrigibility"]),
    ("xrisk-governance", 2017, 2026, 8, 54,
     [(2017, "existential risk"), (2021, "AI governance"), (2023, "responsible scaling")],
     [(2017, "basic")],
     (0.30, 0.20, 0.50),
     ["existential risk", "governance", "responsible scaling", "policy", "catastrophic risk"]),
    ("interpretability", 2016, 2026, 9, 78,
     [(2016, "interpretability"), (2021, "mechanistic interpretability")],
     [(2016, "niche"), (2019, "basic"), (2022, "motor")],
     (0.60, 0.30, 0.10),
     ["interpretability", "circuits", "features", "neurons", "attribution", "probing"]),
    ("sparse-autoencoders", 2023, 2026, 18, 50,
     [(2023, "dictionary learning"), (2024, "sparse autoencoders")],
     [(2023, "emerging"), (2025, "motor")],
     (0.45, 0.50, 0.05),
     ["sparse autoencoders", "dictionary learning", "superposition", "monosemantic", "features"]),
    ("adversarial-robustness", 2016, 2022, 14, 27,
     [(2016, "adversarial robustness")], [(2016, "basic")],
     (0.85, 0.10, 0.05),
     ["adversarial robustness", "adversarial examples", "perturbation", "certified", "attacks"]),
    ("rlhf", 2019, 2026, 10, 72,
     [(2019, "RLHF / human feedback")], [(2019, "emerging"), (2021, "basic"), (2023, "motor")],
     (0.50, 0.40, 0.10),
     ["rlhf", "human feedback", "preference model", "reward model", "fine-tuning"]),
    ("constitutional-ai", 2023, 2026, 22, 46,
     [(2023, "constitutional AI")], [(2023, "emerging"), (2025, "basic")],
     (0.35, 0.60, 0.05),
     ["constitutional ai", "rlaif", "ai feedback", "self-critique", "harmlessness"]),
    ("scalable-oversight", 2018, 2026, 7, 60,
     [(2018, "scalable oversight")], [(2018, "emerging"), (2021, "basic"), (2023, "motor")],
     (0.45, 0.30, 0.25),
     ["scalable oversight", "weak-to-strong", "process supervision", "amplification", "supervision"]),
    ("debate-amplification", 2018, 2021, 8, 14,
     [(2018, "iterated amplification"), (2020, "AI debate")],
     [(2018, "niche")],
     (0.40, 0.15, 0.45),
     ["debate", "amplification", "recursive reward", "factored cognition", "judge"]),
    ("evaluations", 2021, 2026, 12, 68,
     [(2021, "dangerous capabilities"), (2023, "model evaluations")],
     [(2021, "emerging"), (2024, "motor")],
     (0.45, 0.45, 0.10),
     ["evaluations", "dangerous capabilities", "red teaming", "benchmark", "elicitation"]),
    ("deceptive-alignment", 2022, 2026, 10, 35,
     [(2022, "deceptive alignment"), (2024, "model organisms")],
     [(2022, "emerging"), (2025, "niche")],
     (0.35, 0.45, 0.20),
     ["deceptive alignment", "model organisms", "sleeper agents", "sandbagging", "scheming"]),
    ("jailbreaks", 2022, 2026, 16, 42,
     [(2022, "jailbreaks / prompt injection")], [(2022, "niche"), (2024, "basic")],
     (0.60, 0.15, 0.25),
     ["jailbreak", "prompt injection", "guardrails", "refusal", "red teaming"]),
    ("unlearning", 2022, 2025, 10, 18,
     [(2022, "machine unlearning")], [(2022, "niche")],
     (0.70, 0.20, 0.10),
     ["machine unlearning", "model editing", "knowledge editing", "forgetting"]),
    ("ai-control", 2024, 2026, 14, 40,
     [(2024, "AI control")], [(2024, "emerging")],
     (0.35, 0.40, 0.25),
     ["ai control", "monitoring", "untrusted model", "containment", "trusted editing"]),
]

# Cross-lineage flows (strictly one slice forward): merges, splits, emergence.
# (from_key, from_year, to_key, to_year, factor)
TRANSITIONS = [
    ("value-learning", 2018, "scalable-oversight", 2019, 0.50),
    ("reward-modeling", 2019, "rlhf", 2020, 0.55),
    ("interpretability", 2022, "sparse-autoencoders", 2023, 0.42),
    ("rlhf", 2022, "constitutional-ai", 2023, 0.45),
    ("adversarial-robustness", 2022, "evaluations", 2023, 0.40),
    ("debate-amplification", 2021, "scalable-oversight", 2022, 0.50),
    ("scalable-oversight", 2023, "ai-control", 2024, 0.35),
]

_QUAD_CD = {
    "motor": ((0.60, 0.92), (0.60, 0.92)),
    "basic": ((0.55, 0.90), (0.12, 0.42)),
    "niche": ((0.12, 0.42), (0.55, 0.90)),
    "emerging": ((0.10, 0.40), (0.10, 0.40)),
}

# Theme families + shaded colours (spec §12 robustness reads better when related
# themes share a hue). Greens=interpretability, blues=oversight/feedback,
# oranges=evaluation/control, purples=governance/foundations.
FAMILY = {
    "interpretability": "interpretability", "sparse-autoencoders": "interpretability",
    "value-learning": "oversight", "reward-modeling": "oversight", "rlhf": "oversight",
    "scalable-oversight": "oversight", "debate-amplification": "oversight",
    "constitutional-ai": "oversight",
    "adversarial-robustness": "evaluation", "evaluations": "evaluation",
    "jailbreaks": "evaluation", "deceptive-alignment": "evaluation",
    "unlearning": "evaluation", "ai-control": "evaluation",
    "agent-foundations": "foundations", "xrisk-governance": "foundations",
}
COLORS = {
    "interpretability": "#2f9e6f", "sparse-autoencoders": "#65c79b",
    "value-learning": "#86b7e6", "reward-modeling": "#5b97d8", "rlhf": "#2f6fae",
    "scalable-oversight": "#3f7ec4", "debate-amplification": "#9cc0e2",
    "constitutional-ai": "#21507e",
    "adversarial-robustness": "#e6b066", "evaluations": "#d98b2b",
    "jailbreaks": "#c46a3a", "deceptive-alignment": "#b5544d",
    "unlearning": "#d8a25c", "ai-control": "#a83f38",
    "agent-foundations": "#9869c7", "xrisk-governance": "#6f55a6",
}
FAMILY_LABEL = {
    "interpretability": "Interpretability",
    "oversight": "Oversight & feedback",
    "evaluation": "Evaluation & control",
    "foundations": "Governance & foundations",
}


def _at(breakpoints, year):
    chosen = breakpoints[0][1]
    for y, v in breakpoints:
        if year >= y:
            chosen = v
    return chosen


def _lerp(a, b, t):
    return a + (b - a) * t


def _split_layers(size, mix):
    f = round(size * mix[0])
    l = round(size * mix[1])
    forum = max(0, size - f - l)
    return {"formal": f, "lab_report": l, "forum": forum}


def build(cfg: Config, seed: Optional[int] = None) -> tuple[dict, dict, list[dict]]:
    """Return (computed, layer_counts, provenance) for export.write_artifacts."""
    rng = random.Random(seed if seed is not None else cfg.seed)
    years = list(range(cfg.start_year, cfg.end_year + 1))

    node_size: dict[tuple[str, int], int] = {}
    nodes: list[dict] = []
    slice_nodes: dict[int, list[dict]] = {y: [] for y in years}

    for key, start, end, s0, s1, labels, quads, mix, terms in LINEAGES:
        span = max(1, end - start)
        for year in range(start, end + 1):
            if year not in slice_nodes:
                continue
            t = (year - start) / span
            jitter = 1 + rng.uniform(-0.08, 0.08)
            size = max(3, round(_lerp(s0, s1, t) * jitter))
            node_size[(key, year)] = size
            quad = _at(quads, year)
            node = {
                "id": f"{year}::{key}",
                "slice": str(year),
                "label": _at(labels, year),
                "quadrant": quad,
                "size": size,
                "layers": _split_layers(size, mix),
                "terms": terms,
                "_key": key,
                "_quad": quad,
            }
            nodes.append(node)
            slice_nodes[year].append(node)

    # --- links: self-continuation + cross-lineage transitions ---
    links: list[dict] = []
    for key, start, end, *_ in LINEAGES:
        for year in range(start, end):
            a, b = (key, year), (key, year + 1)
            if a in node_size and b in node_size:
                overlap = rng.uniform(0.72, 0.88)
                v = max(1, round(min(node_size[a], node_size[b]) * overlap))
                links.append({"source": f"{year}::{key}", "target": f"{year + 1}::{key}", "value": v})
    for fk, fy, tk, ty, factor in TRANSITIONS:
        if (fk, fy) in node_size and (tk, ty) in node_size:
            v = max(1, round(min(node_size[(fk, fy)], node_size[(tk, ty)]) * factor))
            links.append({"source": f"{fy}::{fk}", "target": f"{ty}::{tk}", "value": v})

    # --- per-slice strategic maps (centrality × density) ---
    slice_maps: dict[str, dict] = {}
    for year in years:
        topics = []
        for n in slice_nodes[year]:
            (clo, chi), (dlo, dhi) = _QUAD_CD[n["_quad"]]
            topics.append(
                {
                    "id": n["id"],
                    "label": n["label"],
                    "centrality": round(rng.uniform(clo, chi), 3),
                    "density": round(rng.uniform(dlo, dhi), 3),
                    "size": n["size"],
                    "quadrant": n["quadrant"],
                    "terms": n["terms"],
                    "layers": n["layers"],
                }
            )
        if topics:
            slice_maps[str(year)] = {"period": str(year), "topics": topics}

    present = [str(y) for y in years if slice_nodes[y]]

    # --- streams: lineage-level attention time series (the new hero artifact) ---
    streams, totals = _streams(nodes, present, rng)
    mix_by_key = {l[0]: l[7] for l in LINEAGES}
    theme_details = _theme_details(streams, rng, mix_by_key)

    # --- trend topics: relative share of the leading lineages ---
    trend = _trend(nodes, present)

    # --- layer counts + provenance ---
    layer_counts = {"formal": 0, "lab_report": 0, "forum": 0}
    for n in nodes:
        for k, v in n["layers"].items():
            layer_counts[k] += v

    for n in nodes:  # strip private fields before export
        n.pop("_key", None)
        n.pop("_quad", None)

    provenance = [
        {"source_name": "synthetic", "source_layer": "formal",
         "pull_date": "n/a", "query": "synthetic storyline (spec §18 face-validity demo)",
         "records": layer_counts["formal"]},
        {"source_name": "synthetic", "source_layer": "forum",
         "pull_date": "n/a", "query": "synthetic storyline", "records": layer_counts["forum"]},
        {"source_name": "synthetic", "source_layer": "lab_report",
         "pull_date": "n/a", "query": "synthetic storyline", "records": layer_counts["lab_report"]},
    ]

    computed = {
        "thematic_evolution": {"nodes": nodes, "links": links},
        "slice_maps": slice_maps,
        "trend_topics": trend,
        "streams": streams,
        "totals": totals,
        "theme_details": theme_details,
        "slices": present,
    }
    return computed, layer_counts, provenance


# Curated subfields for flagship themes (the rest are derived from terms).
SUBFIELDS = {
    "interpretability": [
        "sparse autoencoders & dictionary learning",
        "circuit analysis & attribution",
        "superposition & polysemanticity",
        "probing & representation structure",
    ],
    "sparse-autoencoders": [
        "feature dictionaries", "feature steering", "automated interpretability",
    ],
    "rlhf": [
        "reward modeling", "preference optimization (DPO / PPO)",
        "reward hacking & over-optimization",
    ],
    "constitutional-ai": ["RLAIF", "self-critique & revision", "harmlessness tuning"],
    "scalable-oversight": [
        "weak-to-strong generalization", "debate & amplification",
        "process supervision",
    ],
    "evaluations": [
        "dangerous-capability evals", "red-teaming & elicitation",
        "benchmark design", "autonomy & agentic evals",
    ],
    "deceptive-alignment": [
        "model organisms of misalignment", "sleeper agents & backdoors",
        "sandbagging detection",
    ],
    "ai-control": [
        "monitoring untrusted models", "trusted editing", "control evaluations",
    ],
    "jailbreaks": ["adversarial prompting", "prompt injection", "guardrail robustness"],
    "agent-foundations": ["decision theory", "embedded agency", "corrigibility"],
    "xrisk-governance": [
        "responsible scaling policies", "compute governance", "risk assessment",
    ],
}
_VENUES = {
    "formal": ["arXiv", "NeurIPS", "ICML", "ICLR", "ACL", "EMNLP", "TMLR"],
    "lab_report": ["Anthropic", "Google DeepMind", "OpenAI",
                   "transformer-circuits.pub", "Redwood Research"],
    "forum": ["Alignment Forum", "LessWrong"],
}
_SURNAMES = [
    "Nanda", "Olah", "Burns", "Hubinger", "Bowman", "Chen", "Park", "Saunders",
    "Conmy", "Wang", "Lieberum", "Sharkey", "Marks", "Bricken", "Templeton",
    "Greenblatt", "Shlegeris", "Casper", "Hendrycks", "Cammarata", "Krueger",
    "Ngo", "Cotra", "Steinhardt", "Perez", "Rauker", "Belrose", "Jermyn",
]
_INITIALS = list("ABCDEHJKLMNRST")
_TITLES = [
    "{a}: {b} in large language models",
    "Towards {a} via {b}",
    "{a} and the emergence of {b}",
    "Scaling {a}: a study of {b}",
    "Measuring {a} in frontier models",
    "{a} reveals {b}",
    "A mechanistic account of {a}",
    "On the limits of {a}",
    "{a} for safer {b}",
    "Understanding {a} through {b}",
]


def _title_case(s: str) -> str:
    return s[:1].upper() + s[1:]


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _shades(base_hex, n):
    """n distinguishable shades of a base colour (vary lightness) so a theme's
    subfields read as one family in the sub-river."""
    import colorsys

    base = base_hex.lstrip("#")
    r, g, b = (int(base[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    out = []
    for i in range(max(1, n)):
        ll = l if n == 1 else _clamp(l - 0.12 + 0.30 * (i / (n - 1)), 0.2, 0.82)
        rr, gg, bb = colorsys.hls_to_rgb(h, ll, s)
        out.append("#%02x%02x%02x" % (int(rr * 255), int(gg * 255), int(bb * 255)))
    return out


def _papers(rng, terms, mix, emerged, last, n):
    y0, y1 = int(emerged), int(last)
    papers = []
    for _ in range(n):
        pair = rng.sample(terms, 2) if len(terms) >= 2 else [terms[0], terms[0]]
        a, b = _title_case(pair[0]), pair[1]
        title = rng.choice(_TITLES).format(a=a, b=b)
        layer = rng.choices(
            ["formal", "lab_report", "forum"], weights=list(mix), k=1
        )[0]
        venue = rng.choice(_VENUES[layer])
        year = rng.randint(y0, y1)
        n_auth = rng.randint(1, 4)
        authors = [
            f"{rng.choice(_INITIALS)}. {rng.choice(_SURNAMES)}" for _ in range(n_auth)
        ]
        cites = max(0, int(rng.gauss(40 - 4 * (2026 - year), 30)))
        papers.append(
            {
                "title": title,
                "authors": authors,
                "date": f"{year}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
                "year": str(year),
                "venue": venue,
                "source_layer": layer,
                "url": "https://www.semanticscholar.org/search?q="
                + title.replace(" ", "%20"),
                "citation_count": cites if layer == "formal" else None,
            }
        )
    papers.sort(key=lambda p: (-(p["citation_count"] or 0), p["date"]), reverse=False)
    return papers


def _theme_details(streams, rng, mix_by_key):
    """Per-theme subfields (sub-clusters) each with a representative paper list."""
    details = {}
    for st in streams:
        key = st["key"]
        mix = mix_by_key.get(key, (0.5, 0.3, 0.2))
        labels = SUBFIELDS.get(key)
        if not labels:
            ts = st["terms"]
            labels = [ts[0], ts[min(1, len(ts) - 1)]]
            labels = list(dict.fromkeys(labels))  # dedupe
        # Distribute the theme's per-year attention across subfields, with
        # staggered onsets so subfields emerge over the theme's life (gives the
        # sub-river its own emergence/divergence shape).
        parent = st["series"]
        pslices = [p["slice"] for p in parent]
        psize = [p["size"] for p in parent]
        m = len(labels)
        weights = [rng.uniform(0.7, 1.4) for _ in labels]
        onsets = [round(i * (len(pslices) - 1) / max(1, m)) for i in range(m)]
        raw = [
            [
                weights[i] * (0.08 + 0.92 * _clamp((j - onsets[i] + 1) / 2.0, 0.0, 1.0))
                for j in range(len(pslices))
            ]
            for i in range(m)
        ]
        shades = _shades(st["color"], m)
        subfields = []
        for i, lab in enumerate(labels):
            series = []
            for j, s in enumerate(pslices):
                col = sum(raw[k][j] for k in range(m)) or 1
                sz = round(psize[j] * raw[i][j] / col)
                series.append(
                    {
                        "slice": s,
                        "size": sz,
                        "share": round(sz / (psize[j] or 1), 4),
                        "layers": _split_layers(sz, mix),
                    }
                )
            size = max(3, sum(p["size"] for p in series))
            n_papers = min(28, max(5, size // 9))
            papers = _papers(rng, st["terms"], mix, st["emerged"], st["last"], n_papers)
            slayers = {"formal": 0, "lab_report": 0, "forum": 0}
            for p in papers:
                slayers[p["source_layer"]] += 1
            # Vary subfield quadrants (biased to the parent) so the sub-map has
            # spread; sample centrality/density from the chosen quadrant.
            quads = ["motor", "basic", "niche", "emerging"]
            wts = [3 if q == st["quadrant"] else 1 for q in quads]
            sub_q = rng.choices(quads, weights=wts, k=1)[0]
            (clo, chi), (dlo, dhi) = _QUAD_CD[sub_q]
            subfields.append(
                {
                    "id": f"{key}::sf{i}",
                    "label": lab,
                    "color": shades[i],
                    "size": size,
                    "terms": st["terms"][:5],
                    "quadrant": sub_q,
                    "centrality": round(rng.uniform(clo, chi), 3),
                    "density": round(rng.uniform(dlo, dhi), 3),
                    "layers": slayers,
                    "series": series,
                    "papers": papers,
                }
            )
        subfields.sort(key=lambda s: -s["size"])
        details[key] = {
            "key": key,
            "label": st["label"],
            "family_label": st["family_label"],
            "color": st["color"],
            "total_size": st["total_size"],
            "subfields": subfields,
        }
    return details


def _streams(nodes, present, rng):
    """Group per-slice nodes into theme lineages with a per-year attention
    series (incl. per-layer split) for the streamgraph / emergence views."""
    from collections import defaultdict

    by_key: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        by_key[n["id"].split("::", 1)[1]].append(n)

    totals = [
        {"slice": s, "size": sum(n["size"] for n in nodes if n["slice"] == s)}
        for s in present
    ]
    slice_total = {t["slice"]: t["size"] for t in totals}

    streams = []
    for key, ns in by_key.items():
        ns.sort(key=lambda n: n["slice"])
        series = [
            {
                "slice": n["slice"],
                "size": n["size"],
                "share": round(n["size"] / (slice_total.get(n["slice"], 1) or 1), 4),
                "layers": dict(n["layers"]),
            }
            for n in ns
        ]
        ltot = {"formal": 0, "lab_report": 0, "forum": 0}
        for n in ns:
            for k, v in n["layers"].items():
                ltot[k] += v
        latest = ns[-1]
        (clo, chi), (dlo, dhi) = _QUAD_CD[latest["quadrant"]]
        streams.append(
            {
                "key": key,
                "label": latest["label"],
                "family": FAMILY.get(key, ""),
                "family_label": FAMILY_LABEL.get(FAMILY.get(key, ""), "Other"),
                "color": COLORS.get(key, "#8a95a3"),
                "quadrant": latest["quadrant"],
                "centrality": round(rng.uniform(clo, chi), 3),
                "density": round(rng.uniform(dlo, dhi), 3),
                "emerged": ns[0]["slice"],
                "last": ns[-1]["slice"],
                "peak_size": max(n["size"] for n in ns),
                "total_size": sum(n["size"] for n in ns),
                "terms": latest["terms"],
                "layers": ltot,
                "series": series,
            }
        )
    # Order for pleasant family-grouped stacking + stable colour assignment.
    fam_order = {"interpretability": 0, "oversight": 1, "evaluation": 2, "foundations": 3, "": 4}
    streams.sort(key=lambda s: (fam_order.get(s["family"], 4), s["emerged"], s["key"]))
    return streams, totals


def _trend(nodes, present, top_k=10):
    from collections import defaultdict

    totals: dict[str, int] = defaultdict(int)
    label_for: dict[str, str] = {}
    per_slice: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    slice_total: dict[str, int] = defaultdict(int)
    for n in nodes:
        key = n["id"].split("::", 1)[1]
        totals[key] += n["size"]
        label_for[key] = n["label"]  # last write = latest-year label
        per_slice[n["slice"]][key] += n["size"]
        slice_total[n["slice"]] += n["size"]

    top = sorted(totals, key=totals.get, reverse=True)[:top_k]
    themes = []
    for key in top:
        series = [
            {"slice": s, "frequency": round(per_slice[s].get(key, 0) / (slice_total[s] or 1), 4)}
            for s in present
        ]
        themes.append({"key": key, "label": label_for[key], "series": series})
    return {"themes": themes}

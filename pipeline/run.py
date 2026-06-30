"""Tier A orchestrator (spec §3, §21). Runs the offline pipeline end-to-end and
emits versioned JSON artifacts into public/data. NEVER runs on Netlify.

Examples
--------
  python pipeline/run.py --synthetic           # demo data, no deps/network
  python pipeline/run.py --phase 1             # Layer 1 (formal) MVP
  python pipeline/run.py --phase 2 --no-llm    # + Alignment Forum, keyword-only
  python pipeline/run.py --layers formal forum lab --scope broad
"""
from __future__ import annotations

import argparse
import sys
import time

# Allow both `python -m pipeline.run` and `python pipeline/run.py` — the latter
# has no package context, so bootstrap it before the relative imports resolve.
if __package__ in (None, ""):
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "pipeline"

from . import config
from .config import Config


def _banner(msg: str) -> None:
    print(f"\n=== {msg} ===")


def run_synthetic(cfg: Config) -> None:
    from . import export, synthetic

    _banner("SYNTHETIC BUILD (demo data — not a real corpus)")
    computed, layer_counts, provenance = synthetic.build(cfg)
    sizes = export.write_artifacts(computed, cfg, layer_counts, provenance)
    _report(sizes, layer_counts, computed)


def run_pipeline(cfg: Config, incremental: bool) -> None:
    # Heavy deps imported lazily so --synthetic and the SPA need none of them.
    from . import db, dedup, embed, export
    from . import filter as filt
    from . import thematic_evolution as te
    from .ingest import arxiv, forum, labs, openalex

    _banner(f"PIPELINE  scope={cfg.scope}  {cfg.start_year}-{cfg.end_year}  "
            f"slice={cfg.slice_width}  llm={'on' if cfg.use_llm_classifier else 'off'}")
    print(f"embedding device: {embed.device_hint()}")

    con = db.connect(config.DB_PATH)

    # 1) Ingest each enabled layer (incremental = pull only past the watermark).
    raw = []
    if cfg.enable_formal:
        since = db.newest_date(con, "formal") if incremental else None
        src = arxiv if cfg.formal_source == "arxiv" else openalex
        _banner(f"Layer 1 — {cfg.formal_source} (since {since or cfg.start_year})")
        recs = src.fetch(cfg, since)
        query_desc = "abs-terms+cat" if cfg.formal_source == "arxiv" else "topic+ROR"
        db.record_provenance(con, cfg.formal_source, "formal", query_desc, len(recs))
        raw += recs
        print(f"  {len(recs)} formal records")
    if cfg.enable_forum:
        since = db.newest_date(con, "forum") if incremental else None
        _banner(f"Layer 3 — Alignment Forum (since {since or cfg.start_year})")
        recs = forum.fetch(cfg, since)
        db.record_provenance(con, "alignmentforum", "forum", "af posts", len(recs))
        raw += recs
        print(f"  {len(recs)} forum records")
    if cfg.enable_lab_report:
        since = db.newest_date(con, "lab_report") if incremental else None
        _banner(f"Layer 2 — Lab reports (since {since or cfg.start_year})")
        recs = labs.fetch(cfg, since)
        db.record_provenance(con, "labs", "lab_report", "publication index", len(recs))
        raw += recs
        print(f"  {len(recs)} lab records")

    # 2) Filter — keyword seed (recall) then LLM classifier (precision), cached.
    _banner("Filter — field boundary (spec §7)")
    candidates, rejected = filt.seed_filter(raw, cfg)
    print(f"  seed filter: {len(candidates)} candidates / {len(rejected)} dropped")
    stats = filt.llm_classify(
        candidates, cfg,
        get_cached=lambda d: _cache_get(con, cfg, d),
        set_cached=lambda d, r, why: db.store_classification(con, cfg.classifier_version, d, r, why),
    )
    kept = filt.included(candidates)
    print(f"  PRISMA: {stats.prisma()}")

    # 3) Dedup (within + cross layer; keep earliest date, retain all layers).
    _banner("Deduplicate (spec §8)")
    kept = dedup.deduplicate(kept)
    print(f"  {len(kept)} unique records after dedup")

    # 4) Persist + embed only the new docs (caches do the incremental work).
    db.upsert_records(con, kept)
    _banner("Embed (local sentence-transformers; cached)")
    n_new = embed.ensure_embeddings(con, cfg)
    print(f"  embedded {n_new} new documents")

    # 5) Thematic-evolution compute + export aggregates.
    _banner("Thematic evolution (spec §11)")
    computed = te.compute(con, cfg)
    layer_counts = _layer_counts(con)
    provenance = _provenance(con)
    sizes = export.write_artifacts(computed, cfg, layer_counts, provenance)
    _report(sizes, layer_counts, computed)


def _cache_get(con, cfg, doc_id):
    row = con.execute(
        "SELECT relevant FROM classifier_cache WHERE doc_id = ? AND version = ?",
        [doc_id, cfg.classifier_version],
    ).fetchone()
    return None if row is None else bool(row[0])


def _layer_counts(con) -> dict[str, int]:
    import json

    counts = {"formal": 0, "lab_report": 0, "forum": 0}
    rows = con.execute(
        "SELECT source_layers FROM documents WHERE safety_relevant = TRUE"
    ).fetchall()
    for (layers_json,) in rows:
        for layer in json.loads(layers_json or "[]"):
            counts[layer] = counts.get(layer, 0) + 1
    return counts


def _provenance(con) -> list[dict]:
    rows = con.execute(
        "SELECT source_name, source_layer, pull_date, query, records FROM provenance"
    ).fetchall()
    return [
        {"source_name": r[0], "source_layer": r[1], "pull_date": str(r[2]),
         "query": r[3], "records": r[4]}
        for r in rows
    ]


def _report(sizes: dict[str, int], layer_counts: dict, computed: dict) -> None:
    total = sum(sizes.values())
    n_nodes = len(computed["thematic_evolution"]["nodes"])
    n_links = len(computed["thematic_evolution"]["links"])
    _banner("Artifacts written to public/data")
    for path, b in sorted(sizes.items()):
        print(f"  {path:36s} {b/1024:7.1f} KB")
    print(f"  {'TOTAL':36s} {total/1024:7.1f} KB")
    print(f"\n  graph: {n_nodes} nodes, {n_links} links · "
          f"layers {layer_counts} · slices {len(computed['slices'])}")
    if total > 2_000_000:
        print("  ! >2 MB — check you are exporting aggregates, not raw records (spec §17)")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI-safety thematic-evolution pipeline (Tier A)")
    p.add_argument("--synthetic", action="store_true",
                   help="emit demo artifacts with no deps/network (spec §18)")
    p.add_argument("--phase", type=int, choices=[1, 2, 3, 4],
                   help="1=formal, 2=+forum, 3=+labs, 4=all+harden (spec §21)")
    p.add_argument("--layers", nargs="+", choices=["formal", "forum", "lab"],
                   help="explicit layer selection")
    p.add_argument("--scope", choices=["narrow", "broad"])
    p.add_argument("--formal-source", choices=["openalex", "arxiv"], dest="formal_source",
                   help="Layer 1 source (default openalex; arxiv when OpenAlex is rate-limited)")
    p.add_argument("--slice", choices=["annual", "biannual"], dest="slice_width")
    p.add_argument("--no-llm", action="store_true", help="keyword-only filter")
    p.add_argument("--incremental", action="store_true",
                   help="pull/embed/classify only new docs (spec §16)")
    args = p.parse_args(argv)

    cfg = config.load()
    if args.scope:
        cfg.scope = args.scope
    if args.formal_source:
        cfg.formal_source = args.formal_source
    if args.slice_width:
        cfg.slice_width = args.slice_width
    if args.no_llm:
        cfg.use_llm_classifier = False

    if args.phase:
        cfg.enable_formal = True
        cfg.enable_forum = args.phase >= 2
        cfg.enable_lab_report = args.phase >= 3
    if args.layers:
        cfg.enable_formal = "formal" in args.layers
        cfg.enable_forum = "forum" in args.layers
        cfg.enable_lab_report = "lab" in args.layers

    t0 = time.time()
    if args.synthetic:
        run_synthetic(cfg)
    else:
        run_pipeline(cfg, incremental=args.incremental)
    print(f"\nDone in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Export (spec §13). Writes ONLY summarised structures the front end renders —
aggregates, not raw records. This discipline is what keeps the app deployable
and scalable (spec §2e, §17). Per-document data stays in DuckDB and is never
exported.

Artifacts written to public/data/:
  thematic_evolution.json   { nodes, links }
  slices/<period>.json      per-slice strategic map
  trend_topics.json         { themes }
  metadata.json             corpus size, range, layer counts, provenance, build
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import Config, PUBLIC_DATA


def _write(path: Path, payload: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def write_artifacts(
    computed: dict,
    cfg: Config,
    layer_counts: dict[str, int],
    provenance: list[dict],
    out_dir: Path = PUBLIC_DATA,
) -> dict[str, int]:
    """Write all artifacts; return {relative_path: bytes} for a size report."""
    sizes: dict[str, int] = {}

    sizes["thematic_evolution.json"] = _write(
        out_dir / "thematic_evolution.json", computed["thematic_evolution"]
    )
    sizes["trend_topics.json"] = _write(
        out_dir / "trend_topics.json", computed["trend_topics"]
    )
    # streams.json — lineage-level attention time series (streamgraph + emergence)
    sizes["streams.json"] = _write(
        out_dir / "streams.json",
        {
            "slices": computed["slices"],
            "totals": computed.get("totals", []),
            "streams": computed.get("streams", []),
        },
    )
    for period, payload in computed["slice_maps"].items():
        rel = f"slices/{period}.json"
        sizes[rel] = _write(out_dir / "slices" / f"{period}.json", payload)

    # themes/<key>.json — sharded, lazy-loaded drill-down (subfields + papers).
    # Sharding keeps the static model: the SPA fetches one theme on click, never
    # the whole per-document corpus (spec §17).
    for key, detail in computed.get("theme_details", {}).items():
        rel = f"themes/{key}.json"
        sizes[rel] = _write(out_dir / "themes" / f"{key}.json", detail)

    corpus_size = sum(layer_counts.values())
    metadata = {
        "build_date": _today(),
        "time_range": {"start": str(cfg.start_year), "end": str(cfg.end_year)},
        "slices": computed["slices"],
        "corpus_size": corpus_size,
        "scope": cfg.scope,
        "slice_width": cfg.slice_width,
        "layer_counts": {
            "formal": layer_counts.get("formal", 0),
            "lab_report": layer_counts.get("lab_report", 0),
            "forum": layer_counts.get("forum", 0),
        },
        "embedding_model": cfg.embedding_model,
        "classifier": {
            "model": cfg.llm_model if cfg.use_llm_classifier else "keyword-seed",
            "version": cfg.classifier_version,
            "enabled": cfg.use_llm_classifier,
        },
        "provenance": provenance,
        "notes": (
            "Near-real-time description of an emerging field, not a forecast. "
            "Aggregates only; per-document data stays offline (spec §17, §19)."
        ),
    }
    sizes["metadata.json"] = _write(out_dir / "metadata.json", metadata)
    return sizes


def _today() -> str:
    from datetime import date

    return date.today().isoformat()

# Tier A — Offline compute pipeline

Python pipeline that builds the AI-safety corpus and emits the JSON aggregates
the SPA renders. **Runs on your machine or in CI — never on Netlify** (§3, §14).

## Install

```bash
pip install -r requirements.txt          # heavy: torch, bertopic, duckdb, …
cp ../.env.example ../.env               # OPENALEX_EMAIL; optional ANTHROPIC_API_KEY
```

The **synthetic** path needs none of this — `python run.py --synthetic` uses only
the standard library.

## Run

```bash
# from the repo root, as a module (so relative imports resolve):
python -m pipeline.run --synthetic           # demo artifacts, no deps/network
python -m pipeline.run --phase 1             # Layer 1 (formal) MVP (§21)
python -m pipeline.run --phase 2 --no-llm    # + Alignment Forum, keyword-only
python -m pipeline.run --phase 3             # + lab blogs
python -m pipeline.run --layers formal forum --scope broad --slice biannual
python -m pipeline.run --phase 2 --incremental   # pull/embed/classify only new docs
```

Flags: `--phase {1..4}`, `--layers formal forum lab`, `--scope narrow|broad`,
`--slice annual|biannual`, `--no-llm`, `--incremental`, `--synthetic`.

## Pipeline stages (module → spec §)

| Stage | Module | Spec |
|---|---|---|
| Ingest formal (OpenAlex, ROR + topic) | `ingest/openalex.py` | §5 |
| Ingest forum (ForumMagnum GraphQL) | `ingest/forum.py` | §5 |
| Ingest lab reports (RSS / listing scrape) | `ingest/labs.py` | §5 |
| Normalize → unified schema | `normalize.py`, `schema.py` | §6 |
| Filter: keyword seed → LLM classifier | `filter.py`, `keywords.py` | §7 |
| Deduplicate (within + cross layer) | `dedup.py` | §8 |
| Embed (local sentence-transformers, cached) | `embed.py` | §9 |
| Temporal slicing + thematic evolution | `thematic_evolution.py` | §10, §11 |
| Export aggregates → `public/data/*.json` | `export.py` | §13 |
| Working store (DuckDB) | `db.py` | §13 |

## What it writes (§13)

Only **aggregates** go to `../public/data/` — never raw records:

```
streams.json              { slices, totals, streams:[{key,label,family,color,emerged,last,quadrant,terms,layers,series:[{slice,size,share,layers}]}] }
                          # ^ lineage-level attention time series → streamgraph + emergence timeline (the hero artifact)
themes/<key>.json         { key,label,color,total_size, subfields:[{label,size,terms,quadrant,layers,papers:[{title,authors,date,venue,source_layer,url,citation_count}]}] }
                          # ^ sharded, lazy-loaded recursive drill-down (theme → subfields → papers). NOT the whole corpus.
slices/<period>.json      per-slice strategic map (centrality × density)
thematic_evolution.json   { nodes, links } — per-slice topics + cross-slice flows (lineage source for streams)
trend_topics.json         { themes:[{key,label,series:[{slice,frequency}]}] }
metadata.json             corpus size, range, layer counts, provenance, build date
```

The per-document corpus, abstracts, and embeddings stay in `corpus.db`
(gitignored) and are **never** exported — the discipline that keeps the app
scalable (§17).

## Reproducibility (§16)

- Dependencies pinned in `requirements.txt`.
- Every pull records source, query, and date in the `provenance` table.
- The classifier prompt + model + version live in `filter.py` / `config.py`.
- Stochastic steps (UMAP / HDBSCAN) are seeded via `config.seed`.

## Graceful degradation

Heavy dependencies are imported **lazily**, so:
- `--synthetic` and the SPA work with zero ML/network deps installed.
- With no `ANTHROPIC_API_KEY`, the classifier runs **keyword-only** and says so
  in `metadata.json`.
- If HDBSCAN is unavailable, clustering falls back to agglomerative.

## Optional validation oracle (§11, §18)

If publishing, cross-check the BERTopic themes against
`bibliometrix::thematicEvolution()` on the same corpus. That is **R**, run
offline as a spot-check — not a dependency, and never on Netlify.

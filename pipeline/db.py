"""The offline working store (spec §13): a single-file DuckDB database holding
the normalised corpus, cached embeddings, and classifier results. It supports
incremental refresh (upsert only new docs; embed/classify only the new ones)
and NEVER deploys — Netlify only ever sees public/data/*.json.

DuckDB is imported lazily so the synthetic path (run.py --synthetic) and the
front end work with no heavy dependencies installed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from .schema import Record


def connect(db_path: Path):
    import duckdb  # lazy

    con = duckdb.connect(str(db_path))
    _init_schema(con)
    return con


def _init_schema(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id          VARCHAR PRIMARY KEY,
            source_layer    VARCHAR NOT NULL,
            source_layers   VARCHAR,           -- JSON array (all layers on merge)
            source_name     VARCHAR,
            title           VARCHAR,
            body_text       VARCHAR,
            date            DATE,
            url             VARCHAR,
            doi             VARCHAR,
            arxiv_id        VARCHAR,
            authors         VARCHAR,           -- JSON array
            affiliations    VARCHAR,           -- JSON array
            raw_tags        VARCHAR,           -- JSON array
            citation_count  INTEGER,
            safety_relevant BOOLEAN,
            topic_id        INTEGER,
            pull_date       DATE DEFAULT current_date
        );

        CREATE TABLE IF NOT EXISTS embeddings (
            doc_id     VARCHAR PRIMARY KEY,
            model      VARCHAR,
            vector     VARCHAR              -- JSON array of floats
        );

        CREATE TABLE IF NOT EXISTS classifier_cache (
            doc_id     VARCHAR PRIMARY KEY,
            version    VARCHAR,
            relevant   BOOLEAN,
            rationale  VARCHAR
        );

        CREATE TABLE IF NOT EXISTS provenance (
            source_name  VARCHAR,
            source_layer VARCHAR,
            pull_date    DATE,
            query        VARCHAR,
            records      INTEGER
        );
        """
    )


def upsert_records(con, records: Iterable[Record]) -> int:
    """Idempotent upsert keyed by doc_id (spec §16 incremental refresh)."""
    n = 0
    for r in records:
        con.execute(
            """
            INSERT INTO documents
                (doc_id, source_layer, source_layers, source_name, title,
                 body_text, date, url, doi, arxiv_id, authors, affiliations,
                 raw_tags, citation_count, safety_relevant, topic_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (doc_id) DO UPDATE SET
                source_layers = excluded.source_layers,
                citation_count = excluded.citation_count
            """,
            [
                r.doc_id, r.source_layer, json.dumps(r.source_layers),
                r.source_name, r.title, r.body_text, r.date, r.url, r.doi,
                r.arxiv_id, json.dumps(r.authors), json.dumps(r.affiliations),
                json.dumps(r.raw_tags), r.citation_count, r.safety_relevant,
                r.topic_id,
            ],
        )
        n += 1
    return n


def docs_needing_embedding(con, model: str) -> list[tuple[str, str]]:
    """(doc_id, text) for docs without a cached vector for this model."""
    rows = con.execute(
        """
        SELECT d.doc_id, d.title || '. ' || COALESCE(d.body_text, '')
        FROM documents d
        LEFT JOIN embeddings e
          ON e.doc_id = d.doc_id AND e.model = ?
        WHERE e.doc_id IS NULL
        """,
        [model],
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def store_embeddings(con, model: str, vectors: dict[str, list[float]]) -> None:
    for doc_id, vec in vectors.items():
        con.execute(
            "INSERT OR REPLACE INTO embeddings (doc_id, model, vector) VALUES (?,?,?)",
            [doc_id, model, json.dumps(vec)],
        )


def docs_needing_classification(con, version: str) -> list[tuple[str, str, str]]:
    rows = con.execute(
        """
        SELECT d.doc_id, d.title, COALESCE(d.body_text, '')
        FROM documents d
        LEFT JOIN classifier_cache c
          ON c.doc_id = d.doc_id AND c.version = ?
        WHERE c.doc_id IS NULL
        """,
        [version],
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def store_classification(
    con, version: str, doc_id: str, relevant: bool, rationale: str = ""
) -> None:
    con.execute(
        "INSERT OR REPLACE INTO classifier_cache (doc_id, version, relevant, rationale) VALUES (?,?,?,?)",
        [doc_id, version, relevant, rationale],
    )
    con.execute(
        "UPDATE documents SET safety_relevant = ? WHERE doc_id = ?",
        [relevant, doc_id],
    )


def record_provenance(
    con, source_name: str, source_layer: str, query: str, records: int
) -> None:
    con.execute(
        "INSERT INTO provenance (source_name, source_layer, pull_date, query, records) VALUES (?,?,current_date,?,?)",
        [source_name, source_layer, query, records],
    )


def newest_date(con, source_layer: str) -> Optional[str]:
    """Newest held date for a layer — the watermark for incremental pulls."""
    row = con.execute(
        "SELECT max(date) FROM documents WHERE source_layer = ?", [source_layer]
    ).fetchone()
    return str(row[0]) if row and row[0] else None

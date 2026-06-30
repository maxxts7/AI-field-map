"""Embedding (spec §9). Self-hosted and local by default: BERTopic uses
sentence-transformers (`all-MiniLM-L6-v2`), which downloads once from Hugging
Face then runs entirely on your machine — no per-document network call, nothing
leaves your environment. Do NOT swap in a cloud embedding backend.

Embeddings are CACHED per doc_id in the working store (spec §13): the same text
always yields the same vector, so a refresh only embeds NEW documents. This
turns embedding into a one-time-per-document cost.
"""
from __future__ import annotations

from typing import Optional

from .config import Config

_model_cache: dict[str, object] = {}


def get_model(name: str):
    """Load (once) and reuse a local sentence-transformers model."""
    if name not in _model_cache:
        from sentence_transformers import SentenceTransformer  # lazy

        _model_cache[name] = SentenceTransformer(name)
    return _model_cache[name]


def embed_texts(
    items: list[tuple[str, str]],
    cfg: Config,
    batch_size: int = 64,
) -> dict[str, list[float]]:
    """Embed [(doc_id, text), ...] locally; return {doc_id: vector}."""
    if not items:
        return {}
    model = get_model(cfg.embedding_model)
    ids = [i for i, _ in items]
    texts = [t for _, t in items]
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return {doc_id: vec.tolist() for doc_id, vec in zip(ids, vectors)}


def device_hint() -> str:
    """Report the device sentence-transformers will use (CPU / CUDA / MPS)."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps (Apple Silicon)"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def ensure_embeddings(con, cfg: Config) -> int:
    """Embed only the docs in the store that lack a cached vector for the
    current model. Returns the number newly embedded (spec §16 incremental)."""
    from . import db

    pending = db.docs_needing_embedding(con, cfg.embedding_model)
    if not pending:
        return 0
    vectors = embed_texts(pending, cfg)
    db.store_embeddings(con, cfg.embedding_model, vectors)
    return len(vectors)


def load_matrix(con, cfg: Config, doc_ids: Optional[list[str]] = None):
    """Pull cached vectors back as (doc_ids, numpy matrix) for topic modelling."""
    import json

    import numpy as np

    q = "SELECT doc_id, vector FROM embeddings WHERE model = ?"
    rows = con.execute(q, [cfg.embedding_model]).fetchall()
    wanted = set(doc_ids) if doc_ids else None
    ids, vecs = [], []
    for doc_id, vec in rows:
        if wanted is not None and doc_id not in wanted:
            continue
        ids.append(doc_id)
        vecs.append(json.loads(vec))
    return ids, np.array(vecs, dtype="float32")

"""Tier A — the offline compute pipeline (spec §3).

Ingests, filters, embeds, and topic-models the AI-safety corpus, then emits
versioned JSON aggregates into ../public/data for the static SPA (Tier B) to
render. Runs on your machine or in CI — never on Netlify.
"""

__version__ = "0.2.0"

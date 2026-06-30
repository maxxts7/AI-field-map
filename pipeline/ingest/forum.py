"""Layer 3 — Alignment Forum / LessWrong via the ForumMagnum GraphQL API
(spec §5).

Gotchas handled here: naive wget/curl is blocked (HTTP 403) so we use the API
with a browser-like UA and conservative rate-limiting; we paginate by DATE
WINDOWS rather than large numeric offsets; and we pin/log the query shape
because the API is treated as legacy and its schema shifts occasionally.

requests is imported lazily.
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Optional

from ..config import ALIGNMENT_FORUM_GRAPHQL, Config
from ..normalize import normalize_forum
from ..schema import Record

# Pinned query shape — log this with the pull (spec §16 reproducibility).
POSTS_QUERY = """
query Posts($after: String, $before: String, $limit: Int) {
  posts(input: {terms: {
    view: "new",
    after: $after,
    before: $before,
    limit: $limit,
    af: true
  }}) {
    results {
      _id
      title
      pageUrl
      postedAt
      baseScore
      voteCount
      commentCount
      user { displayName }
      tags { name }
      contents { html }
    }
  }
}
""".strip()

_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "ai-safety-thematic-evolution/0.2 (research; contact in repo)",
}


def fetch(cfg: Config, since: Optional[str] = None) -> list[Record]:
    if not cfg.enable_forum:
        return []
    import requests  # lazy

    start = date.fromisoformat(since) if since else date(cfg.start_year, 1, 1)
    end = date(cfg.end_year, 12, 31)
    out: dict[str, Record] = {}

    window = start
    step = timedelta(days=60)  # date windows, not numeric offsets
    while window <= end and len(out) < cfg.max_forum:
        win_end = min(window + step, end)
        variables = {
            "after": window.isoformat(),
            "before": win_end.isoformat(),
            "limit": 500,
        }
        try:
            resp = requests.post(
                ALIGNMENT_FORUM_GRAPHQL,
                json={"query": POSTS_QUERY, "variables": variables},
                headers=_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
            results = (
                resp.json().get("data", {}).get("posts", {}).get("results", []) or []
            )
        except Exception as exc:  # noqa: BLE001 — keep partial pulls, log & move on
            print(f"  [forum] window {window}..{win_end} failed: {exc}")
            results = []

        for post in results:
            r = normalize_forum(post, source_name="alignmentforum")
            out.setdefault(r.doc_id, r)

        window = win_end + timedelta(days=1)
        time.sleep(cfg.request_delay_s)  # conservative rate limit

    return list(out.values())

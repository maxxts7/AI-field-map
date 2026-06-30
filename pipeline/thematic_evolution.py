"""Thematic-evolution computation (spec §11) — the heart of Tier A.

Primary method: BERTopic-style dynamic topic modelling over the cached
embeddings. Per slice we cluster documents, label each cluster with c-TF-IDF
terms, and score it on Callon CENTRALITY (connectedness to the rest of the
field) and DENSITY (internal development) -> motor / basic / niche / emerging
quadrants. Across consecutive slices we link topics by overlap (inclusion index
on shared terms) and resolve emergence / merge / split / continuation / death.

Output is the graph the SPA renders: nodes (topics per slice) + links (flows),
plus per-slice strategic maps and trend topics. numpy / scikit-learn / hdbscan
are imported lazily; nothing here ships to Netlify.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .config import Config


@dataclass
class Topic:
    id: str
    slice: str
    label: str
    terms: list[str]
    doc_ids: list[str]
    size: int
    layers: dict[str, int]
    centrality: float = 0.0  # raw, pre-normalisation
    density: float = 0.0
    quadrant: str = "emerging"
    term_set: set[str] = field(default_factory=set)


def _cluster(vectors, min_size: int, seed: int):
    """Cluster one slice's embedding matrix. HDBSCAN if available (BERTopic's
    default), else fall back to agglomerative clustering."""
    n = len(vectors)
    if n < min_size:
        return [0] * n  # one topic for a sparse slice
    try:
        import hdbscan

        labels = hdbscan.HDBSCAN(
            min_cluster_size=max(5, min_size // 2), metric="euclidean"
        ).fit_predict(vectors)
        # HDBSCAN marks noise as -1; fold noise into a residual topic.
        return [int(l) for l in labels]
    except Exception:  # noqa: BLE001
        from sklearn.cluster import AgglomerativeClustering

        k = max(2, min(12, n // min_size))
        return list(
            AgglomerativeClustering(n_clusters=k).fit_predict(vectors)
        )


def _label_terms(texts: list[str], top_n: int = 8) -> list[str]:
    """c-TF-IDF-style salient terms for a cluster of documents."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        vec = TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), max_features=2000, min_df=1
        )
        m = vec.fit_transform(texts)
        scores = m.sum(axis=0).A1
        terms = vec.get_feature_names_out()
        order = scores.argsort()[::-1]
        return [terms[i] for i in order[:top_n]]
    except Exception:  # noqa: BLE001
        return []


def _callon_scores(vectors, labels, centroids):
    """Embedding analogue of Callon centrality & density (spec §11):
      density    ~ mean intra-cluster cohesion (internal development),
      centrality ~ mean similarity of a cluster's centroid to the others
                   (connectedness to the rest of the field).
    """
    import numpy as np

    uniq = sorted(set(labels))
    density: dict[int, float] = {}
    for lab in uniq:
        members = vectors[[i for i, l in enumerate(labels) if l == lab]]
        if len(members) > 1:
            c = centroids[lab]
            sims = members @ c  # normalised embeddings -> cosine
            density[lab] = float(sims.mean())
        else:
            density[lab] = 0.0

    cent: dict[int, float] = {}
    cmat = np.array([centroids[l] for l in uniq])
    sim = cmat @ cmat.T
    np.fill_diagonal(sim, 0.0)
    for i, lab in enumerate(uniq):
        cent[lab] = float(sim[i].mean()) if len(uniq) > 1 else 0.5
    return cent, density


def _quadrant(centrality: float, density: float, c_med: float, d_med: float) -> str:
    high_c, high_d = centrality >= c_med, density >= d_med
    if high_c and high_d:
        return "motor"
    if high_c and not high_d:
        return "basic"
    if not high_c and high_d:
        return "niche"
    return "emerging"


def _normalise(values: list[float]) -> dict[int, float]:
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    return {i: (v - lo) / span for i, v in enumerate(values)}


def build_topics_for_slice(
    period: str, docs: list[dict], vectors, cfg: Config
) -> list[Topic]:
    """docs: [{doc_id, text, layers:{...}}], vectors: aligned embedding matrix."""
    import numpy as np

    if not docs:
        return []
    labels = _cluster(vectors, cfg.min_topic_size, cfg.seed)

    members: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        members[lab].append(i)

    centroids: dict[int, "np.ndarray"] = {}
    for lab, idxs in members.items():
        c = vectors[idxs].mean(axis=0)
        norm = np.linalg.norm(c) or 1.0
        centroids[lab] = c / norm

    cent, dens = _callon_scores(vectors, labels, centroids)

    topics: list[Topic] = []
    for lab, idxs in sorted(members.items()):
        if lab == -1 and len(members) > 1:
            continue  # drop HDBSCAN noise when real clusters exist
        texts = [docs[i]["text"] for i in idxs]
        terms = _label_terms(texts)
        layers = {"formal": 0, "lab_report": 0, "forum": 0}
        for i in idxs:
            for layer in docs[i]["layers"]:
                layers[layer] = layers.get(layer, 0) + 1
        topics.append(
            Topic(
                id=f"{period}::t{lab if lab >= 0 else 0}",
                slice=period,
                label=(terms[0] if terms else f"topic {lab}"),
                terms=terms,
                doc_ids=[docs[i]["doc_id"] for i in idxs],
                size=len(idxs),
                layers=layers,
                centrality=cent.get(lab, 0.0),
                density=dens.get(lab, 0.0),
                term_set=set(terms),
            )
        )

    # Quadrants from per-slice medians; normalise scores to 0..1 for the map.
    if topics:
        import statistics

        c_med = statistics.median(t.centrality for t in topics)
        d_med = statistics.median(t.density for t in topics)
        c_norm = _normalise([t.centrality for t in topics])
        d_norm = _normalise([t.density for t in topics])
        for i, t in enumerate(topics):
            t.quadrant = _quadrant(t.centrality, t.density, c_med, d_med)
            t.centrality = round(c_norm[i], 3)
            t.density = round(d_norm[i], 3)
    return topics


def link_slices(a: list[Topic], b: list[Topic]) -> list[dict]:
    """Inclusion index on shared terms between consecutive slices (spec §11).
    inclusion(A,B) = |terms(A) ∩ terms(B)| / min(|A|,|B|)."""
    links: list[dict] = []
    for ta in a:
        for tb in b:
            inter = ta.term_set & tb.term_set
            if not inter:
                continue
            denom = min(len(ta.term_set), len(tb.term_set)) or 1
            inclusion = len(inter) / denom
            if inclusion >= 0.2:
                value = int(round(inclusion * min(ta.size, tb.size)))
                if value > 0:
                    links.append(
                        {"source": ta.id, "target": tb.id, "value": value}
                    )
    return links


def compute(con, cfg: Config) -> dict:
    """Full computation over the working store -> artifact-ready dict."""
    import json

    from .embed import load_matrix

    rows = con.execute(
        """
        SELECT doc_id, title || '. ' || COALESCE(body_text,''), date, source_layers
        FROM documents
        WHERE safety_relevant = TRUE
        """
    ).fetchall()

    ids, matrix = load_matrix(con, cfg)
    index = {doc_id: i for i, doc_id in enumerate(ids)}

    # Bucket docs into slices, keeping only those we have a vector for.
    by_slice: dict[str, list[dict]] = defaultdict(list)
    vec_rows: dict[str, list[int]] = defaultdict(list)
    for doc_id, text, dt, layers_json in rows:
        if doc_id not in index:
            continue
        year = int(str(dt)[:4])
        period = cfg.slice_for_year(year)
        if period is None:
            continue
        layers = json.loads(layers_json) if layers_json else ["formal"]
        by_slice[period].append({"doc_id": doc_id, "text": text, "layers": layers})
        vec_rows[period].append(index[doc_id])

    slice_topics: dict[str, list[Topic]] = {}
    for period in cfg.slices:
        docs = by_slice.get(period, [])
        if not docs:
            continue
        vectors = matrix[vec_rows[period]]
        slice_topics[period] = build_topics_for_slice(period, docs, vectors, cfg)

    result = assemble(slice_topics, cfg)
    stream_docs = result.pop("_stream_docs", {})
    result["theme_details"] = build_theme_details(con, stream_docs, cfg)
    return result


def assemble(slice_topics: dict[str, list["Topic"]], cfg: Config) -> dict:
    """Turn per-slice topics into the four published artifact structures."""
    ordered = [s for s in cfg.slices if s in slice_topics]

    nodes = [
        {
            "id": t.id,
            "slice": t.slice,
            "label": t.label,
            "quadrant": t.quadrant,
            "centrality": t.centrality,
            "density": t.density,
            "size": t.size,
            "layers": t.layers,
            "terms": t.terms,
        }
        for s in ordered
        for t in slice_topics[s]
    ]

    links: list[dict] = []
    for i in range(len(ordered) - 1):
        links += link_slices(slice_topics[ordered[i]], slice_topics[ordered[i + 1]])

    slice_maps = {
        s: {
            "period": s,
            "topics": [
                {
                    "id": t.id,
                    "label": t.label,
                    "centrality": t.centrality,
                    "density": t.density,
                    "size": t.size,
                    "quadrant": t.quadrant,
                    "terms": t.terms,
                    "layers": t.layers,
                }
                for t in slice_topics[s]
            ],
        }
        for s in ordered
    }

    trend = _trend_topics(slice_topics, ordered)
    streams, totals, members = derive_streams(nodes, links, ordered)

    # Map each stream to the doc_ids of its member topics (kept in memory only —
    # never exported in thematic_evolution.json, which stays doc-id-free, §17).
    id2docs = {t.id: t.doc_ids for ts in slice_topics.values() for t in ts}
    by_key = {s["key"]: s for s in streams}
    stream_docs = {}
    for skey, node_ids in members.items():
        meta = by_key.get(skey)
        if not meta:
            continue
        doc_ids: list[str] = []
        for nid in node_ids:
            doc_ids.extend(id2docs.get(nid, []))
        stream_docs[skey] = {
            "label": meta["label"], "color": meta["color"],
            "family_label": meta["family_label"], "quadrant": meta["quadrant"],
            "terms": meta["terms"], "total_size": meta["total_size"],
            "doc_ids": list(dict.fromkeys(doc_ids)),
        }

    return {
        "thematic_evolution": {"nodes": nodes, "links": links},
        "slice_maps": slice_maps,
        "trend_topics": trend,
        "streams": streams,
        "totals": totals,
        "slices": ordered,
        "_stream_docs": stream_docs,  # consumed by compute(), not exported
    }


def build_theme_details(con, stream_docs: dict, cfg, cap_papers: int = 30) -> dict:
    """Per-theme drill-down (spec §17 sharded): sub-cluster each theme's docs,
    label the sub-clusters, and attach a capped representative paper list pulled
    from the working store. Imported lazily; nothing here ships to Netlify."""
    from .embed import load_matrix

    details: dict[str, dict] = {}
    for skey, meta in stream_docs.items():
        doc_ids = meta["doc_ids"]
        subfields = []
        if doc_ids:
            ids, matrix = load_matrix(con, cfg, doc_ids)
            sub_labels = _subcluster(matrix, ids)
            metadata = _fetch_paper_meta(con, ids)
            groups: dict[int, list[str]] = {}
            for did, lab in zip(ids, sub_labels):
                groups.setdefault(lab, []).append(did)
            shades = _shades(meta["color"], len(groups))
            cmap, dmap, cmed, dmed = _strategic_coords(matrix, sub_labels)
            for gi, (lab, gids) in enumerate(sorted(groups.items())):
                titles = [metadata[d]["title"] for d in gids if d in metadata]
                terms = _label_terms(titles, top_n=5) or meta["terms"][:5]
                papers = _papers_for(gids, metadata, cap_papers)
                series = _series_for(gids, metadata, cfg)
                layers = {"formal": 0, "lab_report": 0, "forum": 0}
                for pt in series:
                    for k in layers:
                        layers[k] += pt["layers"][k]
                ce, de = cmap.get(lab, 0.5), dmap.get(lab, 0.5)
                subfields.append({
                    "id": f"{skey}::sf{gi}",
                    "label": terms[0] if terms else f"subfield {gi}",
                    "color": shades[gi],
                    "size": len(gids),
                    "terms": terms,
                    "quadrant": _quadrant(ce, de, cmed, dmed),
                    "centrality": round(ce, 3),
                    "density": round(de, 3),
                    "layers": layers,
                    "series": series,
                    "papers": papers,
                })
            subfields.sort(key=lambda s: -s["size"])
        details[skey] = {
            "key": skey, "label": meta["label"],
            "family_label": meta["family_label"], "color": meta["color"],
            "total_size": meta["total_size"], "subfields": subfields,
        }
    return details


def _shades(base_hex: str, n: int) -> list[str]:
    """n lightness-varied shades of a base colour (subfields of one theme)."""
    import colorsys

    base = base_hex.lstrip("#")
    try:
        r, g, b = (int(base[i : i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return _palette(n)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    out = []
    for i in range(max(1, n)):
        ll = l if n <= 1 else max(0.2, min(0.82, l - 0.12 + 0.30 * (i / (n - 1))))
        rr, gg, bb = colorsys.hls_to_rgb(h, ll, s)
        out.append(f"#{int(rr*255):02x}{int(gg*255):02x}{int(bb*255):02x}")
    return out


def _strategic_coords(matrix, labels):
    """Callon centrality/density for sub-clusters (embedding analogue, §11),
    normalised 0..1, plus the medians for quadrant assignment."""
    import statistics

    import numpy as np

    uniq = sorted(set(labels))
    centroids = {}
    for lab in uniq:
        rows = matrix[[i for i, l in enumerate(labels) if l == lab]]
        c = rows.mean(axis=0)
        centroids[lab] = c / (np.linalg.norm(c) or 1.0)
    cent, dens = _callon_scores(matrix, labels, centroids)
    cn = _normalise([cent[l] for l in uniq])
    dn = _normalise([dens[l] for l in uniq])
    cmap = {uniq[i]: cn[i] for i in range(len(uniq))}
    dmap = {uniq[i]: dn[i] for i in range(len(uniq))}
    cmed = statistics.median(cmap.values()) if cmap else 0.5
    dmed = statistics.median(dmap.values()) if dmap else 0.5
    return cmap, dmap, cmed, dmed


def _series_for(gids: list[str], metadata: dict, cfg) -> list[dict]:
    """Per-slice attention of a sub-cluster, from its documents' dates."""
    sm: dict[str, dict] = {}
    for d in gids:
        m = metadata.get(d)
        if not m or not m.get("date"):
            continue
        per = cfg.slice_for_year(int(m["date"][:4]))
        if per is None:
            continue
        e = sm.setdefault(per, {"size": 0, "layers": {"formal": 0, "lab_report": 0, "forum": 0}})
        e["size"] += 1
        e["layers"][m["source_layer"]] = e["layers"].get(m["source_layer"], 0) + 1
    return [
        {"slice": s, "size": sm[s]["size"], "share": 0.0, "layers": sm[s]["layers"]}
        for s in sorted(sm)
    ]


def _subcluster(matrix, ids: list[str]) -> list[int]:
    n = len(ids)
    if n < 12:
        return [0] * n
    k = max(2, min(5, n // 40))
    from sklearn.cluster import KMeans

    return list(KMeans(n_clusters=k, n_init=4, random_state=0).fit_predict(matrix))


def _fetch_paper_meta(con, ids: list[str]) -> dict:
    import json

    placeholders = ",".join(["?"] * len(ids))
    rows = con.execute(
        f"""SELECT doc_id, title, authors, date, url, doi, source_name,
                   source_layer, citation_count
            FROM documents WHERE doc_id IN ({placeholders})""",
        ids,
    ).fetchall()
    out = {}
    for r in rows:
        out[r[0]] = {
            "title": r[1] or "", "authors": json.loads(r[2] or "[]"),
            "date": str(r[3]) if r[3] else "", "url": r[4] or "",
            "doi": r[5] or "", "venue": r[6] or "", "source_layer": r[7],
            "citation_count": r[8],
        }
    return out


def _papers_for(gids: list[str], metadata: dict, cap: int) -> list[dict]:
    items = [metadata[d] for d in gids if d in metadata]
    items.sort(key=lambda m: ((m["citation_count"] or 0), m["date"]), reverse=True)
    papers = []
    for m in items[:cap]:
        url = m["url"] or (f"https://doi.org/{m['doi']}" if m["doi"] else "")
        papers.append({
            "title": m["title"], "authors": m["authors"],
            "date": m["date"], "year": m["date"][:4] if m["date"] else "",
            "venue": m["venue"], "source_layer": m["source_layer"],
            "url": url, "citation_count": m["citation_count"],
        })
    return papers


def _palette(n: int) -> list[str]:
    """n well-spaced colours for lineages the real pipeline can't family-group."""
    import colorsys

    out = []
    for i in range(max(1, n)):
        h = (i * 0.618033988749895) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, 0.5, 0.55)
        out.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")
    return out


def derive_streams(nodes: list[dict], links: list[dict], ordered: list[str]) -> tuple[list[dict], list[dict]]:
    """Chain per-slice topics into theme lineages by the MAIN PATH: each topic
    continues the stream of its strongest unclaimed predecessor, so continuations
    form streams, the dominant branch of a split continues the parent, and the
    other branch / a fresh topic starts a new stream (emergence). Returns
    (streams, totals) shaped like the streamgraph artifact (spec §11)."""
    from collections import defaultdict

    by_id = {n["id"]: n for n in nodes}
    by_slice: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        by_slice[n["slice"]].append(n)
    incoming: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for l in links:
        incoming[l["target"]].append((l["source"], l["value"]))

    stream_of: dict[str, int] = {}
    claimed: set[str] = set()
    next_id = 0
    for s in ordered:
        for n in sorted(by_slice.get(s, []), key=lambda x: -x["size"]):
            preds = sorted(incoming.get(n["id"], []), key=lambda p: -p[1])
            chosen = next((src for src, _ in preds if src not in claimed and src in stream_of), None)
            if chosen is not None:
                stream_of[n["id"]] = stream_of[chosen]
                claimed.add(chosen)
            else:
                stream_of[n["id"]] = next_id
                next_id += 1

    members: dict[int, list[dict]] = defaultdict(list)
    for node_id, sid in stream_of.items():
        members[sid].append(by_id[node_id])

    totals = [{"slice": s, "size": sum(n["size"] for n in by_slice.get(s, []))} for s in ordered]
    slice_total = {t["slice"]: t["size"] for t in totals}

    colors = _palette(len(members))
    members_out: dict[str, list[str]] = {}
    streams = []
    for ci, (_sid, ns) in enumerate(sorted(members.items())):
        members_out[f"s{ci}"] = [n["id"] for n in ns]
        ns.sort(key=lambda n: n["slice"])
        per_slice_size: dict[str, int] = defaultdict(int)
        per_slice_layers: dict[str, dict] = defaultdict(lambda: {"formal": 0, "lab_report": 0, "forum": 0})
        for n in ns:
            per_slice_size[n["slice"]] += n["size"]
            for k, v in n["layers"].items():
                per_slice_layers[n["slice"]][k] += v
        active = sorted(per_slice_size)
        series = [
            {"slice": s, "size": per_slice_size[s],
             "share": round(per_slice_size[s] / (slice_total.get(s, 1) or 1), 4),
             "layers": per_slice_layers[s]}
            for s in active
        ]
        ltot = {"formal": 0, "lab_report": 0, "forum": 0}
        for s in active:
            for k in ltot:
                ltot[k] += per_slice_layers[s][k]
        latest = ns[-1]
        # Stream strategic coords = mean of member topics (nodes carry 0..1
        # centrality/density from the per-slice strategic diagrams).
        cen = sum(n.get("centrality", 0.5) for n in ns) / len(ns)
        den = sum(n.get("density", 0.5) for n in ns) / len(ns)
        streams.append(
            {
                "key": f"s{ci}", "label": latest["label"], "family": "",
                "family_label": "Other", "color": colors[ci],
                "quadrant": latest["quadrant"],
                "centrality": round(cen, 3), "density": round(den, 3),
                "emerged": active[0], "last": active[-1],
                "peak_size": max(per_slice_size.values()),
                "total_size": sum(per_slice_size.values()),
                "terms": latest["terms"], "layers": ltot, "series": series,
            }
        )
    streams.sort(key=lambda s: (s["emerged"], -s["total_size"]))
    return streams, totals, members_out


def _trend_topics(slice_topics, ordered, top_k: int = 10) -> dict:
    """Relative share of the leading themes across slices (spec §13)."""
    # Rank themes by total size; track each label's per-slice share.
    totals: dict[str, int] = defaultdict(int)
    per_slice_label: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    slice_total: dict[str, int] = defaultdict(int)
    for s in ordered:
        for t in slice_topics[s]:
            key = t.label
            totals[key] += t.size
            per_slice_label[s][key] += t.size
            slice_total[s] += t.size

    top = sorted(totals, key=totals.get, reverse=True)[:top_k]
    themes = []
    for label in top:
        series = [
            {
                "slice": s,
                "frequency": round(
                    per_slice_label[s].get(label, 0) / (slice_total[s] or 1), 4
                ),
            }
            for s in ordered
        ]
        themes.append(
            {"key": label.replace(" ", "-"), "label": label, "series": series}
        )
    return {"themes": themes}

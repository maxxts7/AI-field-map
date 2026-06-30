"""Per-paper LINEAGE + FUTURE-DIRECTION enrichment — a companion to taxonomy.py.

The corpus has no real citation graph (citation_count is empty), so every link
here is *inferred*. Two products, both shipped as static JSON the SPA reads:

  1. LINEAGE — for each tagged paper, a chronological chain of antecedent work
     reaching back to a curated CANONICAL anchor. Chain edges are the nearest
     earlier neighbour in embedding space (cosine on the cached MiniLM vectors),
     nudged to step gradually back in time so the chain reads as a lineage rather
     than one global jump. Each step carries a one-line significance gloss.

  2. FUTURE — a 5th facet built with taxonomy.py's exact hierarchical-tagging
     machinery: a tree of future research directions rooted at "grand-challenge"
     end-states (the proverbial condition — robustly safe, aligned, controllable
     AI). Each paper is tagged into the direction it most advances, and gets a
     one-sentence forward BRIDGE linking its present contribution to that future.

Writes / merges (idempotent; intermediates cached under data/raw/lineage/):
  public/data/taxonomy/facets.json       (+ `future` facet tree)
  public/data/taxonomy/paper_tags.json   (+ `future` path per paper)
  public/data/taxonomy/lineage.json       doc_id -> {anc:[...], anchor:{...}}
  public/data/taxonomy/paper_detail.json  doc_id -> {sig, bridge, anchor, future}

Haiku 4.5 + Batch API, reusing taxonomy.py's Budget, key handling and builders.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pipeline.taxonomy as tax

REPO = Path(__file__).resolve().parent.parent
DB_PATH = Path(__file__).resolve().parent / "corpus.db"
OUT_DIR = REPO / "public" / "data" / "taxonomy"
DESC_DIR = OUT_DIR / "desc"   # one {does,connects,enables} file per paper, lazy-loaded
STATE_DIR = Path(__file__).resolve().parent / "data" / "raw" / "lineage"
FUTURE_STATE = Path(__file__).resolve().parent / "data" / "raw" / "taxonomy" / "future.json"

# per-paper long description tuning
DESC_WORDS = 150     # target words per field (does / connects / enables)
DESC_CHARS = 1400    # hard clip per field when assembling artifacts

# lineage chain tuning
MIN_SIM = 0.40       # cosine floor for an edge to count as an antecedent
MAX_HOPS = 6         # corpus ancestors before we attach the canonical anchor
CANON_YEAR = 2019    # once a chain reaches this year or earlier, stop and anchor
TIME_DECAY = 0.03    # per-year penalty: prefer the nearer-in-time related parent


# --- the future facet (fixed root = the "proverbial conditions") ----------
FUTURE_FACET = {
    "title": "Future direction",
    "desc": ("the future research direction this paper most advances, on the path "
             "toward robustly safe, aligned and controllable AI"),
    "seed": "",
    "root_children": [
        {"slug": "verifiable-safety", "label": "Provable & verifiable safety",
         "description": "Toward formal guarantees and verification that a system provably satisfies its safety specification."},
        {"slug": "scalable-oversight", "label": "Scalable oversight of superhuman AI",
         "description": "Toward supervising, eliciting and evaluating systems more capable than their human overseers."},
        {"slug": "robust-alignment", "label": "Robust alignment under pressure",
         "description": "Toward alignment that holds under distribution shift, optimization pressure, goal misgeneralization and deception."},
        {"slug": "transparency-at-scale", "label": "Mechanistic transparency at scale",
         "description": "Toward fully reverse-engineering model internals and computation at frontier scale."},
        {"slug": "control-containment", "label": "Reliable control & containment",
         "description": "Toward runtime control protocols and containment that stay safe even if the model is misaligned."},
        {"slug": "trustworthy-evaluation", "label": "Trustworthy evaluation & auditing",
         "description": "Toward evaluations, audits and safety cases we can trust to certify a system before deployment."},
        {"slug": "misuse-resilience", "label": "Resilience to misuse & adversaries",
         "description": "Toward systems robust to jailbreaks, weaponization and adversarial misuse at deployment scale."},
        {"slug": "governance-coordination", "label": "Governance & coordination",
         "description": "Toward institutions, norms, standards and incentives that coordinate safe development across actors."},
    ],
}

# --- curated canonical anchors (the terminus of every lineage) ------------
ANCHORS = [
    {"id": "concrete-problems", "t": "Concrete Problems in AI Safety", "a": "Amodei, Olah, et al.",
     "y": "2016", "u": "https://arxiv.org/abs/1606.06565",
     "sig": "Framed the canonical agenda of accident risks — safe exploration, robustness to distributional shift, avoiding negative side effects, scalable oversight — that most empirical safety work still organises around."},
    {"id": "deep-rl-preferences", "t": "Deep Reinforcement Learning from Human Preferences", "a": "Christiano et al.",
     "y": "2017", "u": "https://arxiv.org/abs/1706.03741",
     "sig": "Showed complex behaviour can be trained from human preference comparisons rather than hand-coded rewards — the seed of RLHF and modern preference-based alignment."},
    {"id": "attention-is-all-you-need", "t": "Attention Is All You Need", "a": "Vaswani et al.",
     "y": "2017", "u": "https://arxiv.org/abs/1706.03762",
     "sig": "Introduced the Transformer, the architectural substrate every frontier model — and therefore every modern safety problem — is built on."},
    {"id": "ai-safety-via-debate", "t": "AI Safety via Debate", "a": "Irving, Christiano, Amodei",
     "y": "2018", "u": "https://arxiv.org/abs/1805.00899",
     "sig": "Proposed using adversarial debate between AIs to let humans supervise tasks beyond their own competence — a foundational scalable-oversight proposal."},
    {"id": "risks-from-learned-optimization", "t": "Risks from Learned Optimization in Advanced ML Systems", "a": "Hubinger et al.",
     "y": "2019", "u": "https://arxiv.org/abs/1906.01820",
     "sig": "Named mesa-optimization and inner misalignment — why a trained system can pursue goals different from its training objective — the conceptual root of deception research."},
    {"id": "zoom-in-circuits", "t": "Zoom In: An Introduction to Circuits", "a": "Olah et al.",
     "y": "2020", "u": "https://distill.pub/2020/circuits/zoom-in/",
     "sig": "Launched the circuits program — reverse-engineering networks into human-understandable features and connections — the basis of mechanistic interpretability."},
    {"id": "instructgpt", "t": "Training Language Models to Follow Instructions with Human Feedback", "a": "Ouyang et al.",
     "y": "2022", "u": "https://arxiv.org/abs/2203.02155",
     "sig": "Operationalised RLHF at scale (InstructGPT), making preference fine-tuning the dominant post-training alignment method for deployed LLMs."},
    {"id": "constitutional-ai", "t": "Constitutional AI: Harmlessness from AI Feedback", "a": "Bai et al.",
     "y": "2022", "u": "https://arxiv.org/abs/2212.08073",
     "sig": "Replaced much human feedback with AI feedback against an explicit constitution — a template for scalable, principle-driven alignment (RLAIF)."},
    {"id": "model-evals-extreme-risks", "t": "Model Evaluation for Extreme Risks", "a": "Shevlane et al.",
     "y": "2023", "u": "https://arxiv.org/abs/2305.15324",
     "sig": "Argued dangerous-capability and alignment evaluations must gate frontier deployment — the framing behind today's evals, red-teaming and safety cases."},
    {"id": "universal-transferable-attacks", "t": "Universal and Transferable Adversarial Attacks on Aligned Language Models", "a": "Zou et al.",
     "y": "2023", "u": "https://arxiv.org/abs/2307.15043",
     "sig": "Demonstrated automated, transferable jailbreak suffixes that defeat alignment training — the reference point for adversarial-robustness and jailbreak research."},
]
ANCHOR_IDS = [a["id"] for a in ANCHORS]
ANCHOR_BY_ID = {a["id"]: a for a in ANCHORS}


def clip(s: str, n: int) -> str:
    """Trim to <=n chars at a word boundary, adding an ellipsis if cut."""
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "…"


# --- corpus access --------------------------------------------------------
def load_corpus(con):
    """All docs (any year) -> meta; and a normalized embedding matrix."""
    import numpy as np

    rows = con.execute(
        "SELECT d.doc_id, d.title, CAST(d.date AS VARCHAR), d.url, d.source_name, "
        "d.source_layer, e.vector "
        "FROM documents d JOIN embeddings e ON d.doc_id = e.doc_id"
    ).fetchall()
    ids, meta, vecs = [], {}, []
    for doc_id, title, date, url, source, layer, vector in rows:
        v = np.asarray(json.loads(vector), dtype=np.float32)
        ids.append(doc_id)
        meta[doc_id] = {"t": title or "", "d": date, "y": (date or "0000")[:4],
                        "u": url or "", "v": source or "", "l": layer}
        vecs.append(v)
    M = np.vstack(vecs)
    M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)
    date_int = np.array([int((meta[i]["d"] or "0").replace("-", "")) for i in ids], dtype=np.int64)
    idx = {i: k for k, i in enumerate(ids)}
    return ids, meta, M, date_int, idx


def load_meta_for(con, ids):
    """doc_id -> {title, abstract, date, layer} for an arbitrary set of ids.

    load_corpus() omits body_text, so antecedents would otherwise be described
    from their title alone; this fetches the abstract for every paper we gloss.
    """
    ids = list(ids)
    if not ids:
        return {}
    qs = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT doc_id, title, COALESCE(body_text,''), CAST(date AS VARCHAR), source_layer "
        f"FROM documents WHERE doc_id IN ({qs})", ids
    ).fetchall()
    return {r[0]: {"title": r[1] or "", "abstract": r[2] or "", "date": r[3], "layer": r[4]}
            for r in rows}


def build_chain(target, ids, M, date_int, idx):
    """Nearest-earlier-neighbour ancestry. Returns ancestor ids, NEWEST->oldest."""
    import numpy as np

    chain, visited = [], {idx[target]}
    cur = idx[target]
    for _ in range(MAX_HOPS):
        sims = M @ M[cur]
        older = date_int < date_int[cur]
        ok = older & (sims >= MIN_SIM)
        ok[list(visited)] = False
        if not ok.any():
            break
        gap_years = np.clip((date_int[cur] - date_int) / 10000.0, 0, None)
        score = np.where(ok, sims - TIME_DECAY * gap_years, -np.inf)
        j = int(np.argmax(score))
        chain.append({"i": ids[j], "sim": round(float(sims[j]), 3)})
        visited.add(j)
        cur = j
        if int(date_int[j] // 10000) <= CANON_YEAR:
            break
    return chain


# --- generic batch runner (arbitrary per-job schema) ----------------------
def run_batch(client, jobs, budget, label):
    """jobs: [{cid, system, user, schema, max_tokens}]. -> {cid: parsed_dict}."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    reqs = [
        Request(custom_id=j["cid"], params=MessageCreateParamsNonStreaming(
            model=tax.MODEL, max_tokens=j.get("max_tokens", 160), system=j["system"],
            messages=[{"role": "user", "content": j["user"]}],
            output_config={"format": {"type": "json_schema", "schema": j["schema"]}},
        ))
        for j in jobs
    ]
    batch = client.messages.batches.create(requests=reqs)
    print(f"   [{label}] batch {batch.id} ({len(reqs)} reqs) submitted", flush=True)
    while True:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        time.sleep(12)
    out, in_tok, out_tok = {}, 0, 0
    for r in client.messages.batches.results(batch.id):
        if r.result.type == "succeeded":
            m = r.result.message
            in_tok += m.usage.input_tokens
            out_tok += m.usage.output_tokens
            try:
                out[r.custom_id] = json.loads(m.content[0].text)
            except Exception:  # noqa: BLE001
                out[r.custom_id] = {}
        else:
            out[r.custom_id] = {}
    budget.add(in_tok, out_tok, batch=True)
    print(f"   [{label}] done: {b.request_counts.succeeded} ok / {b.request_counts.errored} err "
          f"· spend ${budget.spent:.2f}", flush=True)
    return out


def sig_jobs(need, meta_full, tagged):
    """One significance gloss per paper (reused everywhere it appears)."""
    schema = {"type": "object", "properties": {"sig": {"type": "string"}},
              "required": ["sig"], "additionalProperties": False}
    system = (
        "You write one-sentence significance glosses for AI/ML research papers, for a "
        "lineage view where this paper is shown as an antecedent of later work.\n"
        "In <=28 words, state concretely what THIS paper contributed or established — the "
        "reusable idea, method or result others would build on. No hedging, no 'this paper', "
        "no restating the title verbatim."
    )
    jobs = []
    for d in need:
        m = tagged.get(d) or meta_full.get(d)
        if not m:
            continue
        title = m.get("title") or m.get("t") or ""
        abstract = (m.get("abstract") or "")[:tax.ABSTRACT_CHARS]
        user = f"TITLE: {title}\n\nABSTRACT: {abstract}"
        jobs.append({"cid": d, "system": system, "user": user, "schema": schema, "max_tokens": 90})
    return jobs


def desc_jobs(need, meta):
    """A long, three-part description per paper, used in the detail overlay.

    Each field is one cohesive paragraph of ~DESC_WORDS words:
      does     — what the paper itself contributes (grounded in the abstract);
      connects — how it builds on / responds to prior work;
      enables  — what it sets up or makes possible next.
    The last two are necessarily interpretive: an abstract rarely spells out its
    antecedents or downstream impact, so the model reasons from field knowledge.
    """
    schema = {
        "type": "object",
        "properties": {
            "does": {"type": "string"},
            "connects": {"type": "string"},
            "enables": {"type": "string"},
        },
        "required": ["does", "connects", "enables"], "additionalProperties": False,
    }
    system = (
        "You write structured descriptions of AI-safety / ML research papers for an "
        "interactive map where readers explore how work connects across time.\n"
        "From the paper's title and abstract, write THREE fields, each a SINGLE cohesive "
        f"paragraph of about {DESC_WORDS} words (roughly {DESC_WORDS - 25}-{DESC_WORDS + 25}):\n"
        "- does: what THIS paper actually does — its core contribution, method and main "
        "results or claims. Concrete and grounded in the abstract.\n"
        "- connects: how this work connects to and builds on PRIOR research — the lines of "
        "work, problems and earlier methods it extends, combines or responds to. Draw on "
        "general knowledge of the field; be specific and plausible, never vague.\n"
        "- enables: what this work enables or points toward in the FUTURE — follow-up "
        "directions, capabilities, open problems or applications it could set up.\n"
        "Write clear expository prose, present tense, no bullet points, no headings, no "
        "markdown, do not repeat the title verbatim, and avoid hedging filler."
    )
    jobs = []
    for d in need:
        m = meta.get(d)
        if not m:
            continue
        user = f"TITLE: {m.get('title', '')}\n\nABSTRACT: {(m.get('abstract') or '')[:tax.ABSTRACT_CHARS]}"
        jobs.append({"cid": d, "system": system, "user": user, "schema": schema, "max_tokens": 1000})
    return jobs


def bridge_jobs(tagged, future_paths, future_leaf_meta):
    """Per tagged paper: forward bridge to its future direction + canonical anchor."""
    anchor_opts = "\n".join(f"- {a['id']}: {a['t']} ({a['y']}) — {a['sig'][:90]}" for a in ANCHORS)
    schema = {
        "type": "object",
        "properties": {
            "bridge": {"type": "string"},
            "anchor": {"type": "string", "enum": ANCHOR_IDS},
        },
        "required": ["bridge", "anchor"], "additionalProperties": False,
    }
    jobs = []
    for d, p in tagged.items():
        leaf = future_paths.get(d)
        lm = future_leaf_meta.get(leaf, {})
        future_label = lm.get("label", "a future safety direction")
        future_desc = lm.get("description", "")
        system = (
            "You connect an AI-safety paper to where its line of work is heading.\n"
            f"This paper has been routed to the future direction \"{future_label}\": {future_desc}\n"
            "Return two things:\n"
            "1. bridge: ONE sentence (<=32 words) stating how this paper is a stepping-stone toward "
            "that future direction — what concrete next step or open problem it sets up. Forward-looking, specific.\n"
            "2. anchor: choose the single canonical foundational work this research line most descends from:\n"
            f"{anchor_opts}"
        )
        user = f"TITLE: {p['title']}\n\nABSTRACT: {p['abstract'][:tax.ABSTRACT_CHARS]}"
        jobs.append({"cid": d, "system": system, "user": user, "schema": schema, "max_tokens": 130})
    return jobs


def leaf_meta(tree):
    """node-id -> {label, description} for every node in a facet tree."""
    out = {}

    def walk(n):
        out[n["id"]] = {"label": n["label"], "description": n.get("description", "")}
        for c in n.get("children", []):
            walk(c)

    walk(tree)
    return out


def main(argv=None) -> int:
    import duckdb

    p = argparse.ArgumentParser(description="Per-paper lineage + future-direction enrichment")
    p.add_argument("--since", default="2026-01-01", help="must match taxonomy.py's --since")
    p.add_argument("--limit", type=int, default=0, help="prototype: cap tagged-paper count")
    p.add_argument("--skip-future", action="store_true", help="reuse cached future facet only")
    args = p.parse_args(argv)

    tax.load_key()
    import anthropic

    client = anthropic.Anthropic()
    con = duckdb.connect(str(DB_PATH), read_only=True)

    where = (f"safety_relevant=TRUE AND (source_layer='lab_report' "
             f"OR (source_layer='formal' AND CAST(date AS VARCHAR) >= '{args.since}'))")
    tagged = tax.get_papers(con, where)  # doc_id -> {title, abstract, date, layer}
    if args.limit:
        tagged = dict(list(tagged.items())[: args.limit])
    print(f"tagged papers: {len(tagged)} · since {args.since}", flush=True)

    budget = tax.Budget()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # === 1) future facet (cached like taxonomy.py) ========================
    if FUTURE_STATE.exists():
        print("future facet: loading cached state", flush=True)
        saved = json.loads(FUTURE_STATE.read_text(encoding="utf-8"))
        future_tree, future_paths = saved["tree"], saved["paths"]
    else:
        print(f"\n=== building future facet === (spend ${budget.spent:.2f})", flush=True)
        tax.FACETS["future"] = FUTURE_FACET
        nodes = tax.build_facet(client, "future", tagged, budget)
        future_tree = tax.to_tree(nodes, "future")
        future_paths = tax.leaf_paths(nodes, "future")
        FUTURE_STATE.parent.mkdir(parents=True, exist_ok=True)
        FUTURE_STATE.write_text(json.dumps({"tree": future_tree, "paths": future_paths}),
                                encoding="utf-8")
        n_leaves = sum(1 for _ in tax._iter_leaves(future_tree))
        print(f"   future facet done · {n_leaves} leaves · spend ${budget.spent:.2f}", flush=True)
    fmeta = leaf_meta(future_tree)

    # === 2) lineage chains (deterministic, from embeddings) ===============
    print("\n=== building lineage chains ===", flush=True)
    ids, meta_full, M, date_int, idx = load_corpus(con)
    chains_path = STATE_DIR / "chains.json"
    if chains_path.exists():
        chains = json.loads(chains_path.read_text(encoding="utf-8"))
    else:
        chains = {}
        for n, d in enumerate(tagged):
            if d not in idx:
                continue
            chains[d] = build_chain(d, ids, M, date_int, idx)
            if (n + 1) % 250 == 0:
                print(f"   chained {n + 1}/{len(tagged)}", flush=True)
        chains_path.write_text(json.dumps(chains), encoding="utf-8")
    anc_ids = {c["i"] for ch in chains.values() for c in ch}
    print(f"   {len(chains)} chains · {len(anc_ids)} unique antecedents", flush=True)

    # === 3) significance glosses for everything shown (cached) ============
    sig_path = STATE_DIR / "sig.json"
    sig = json.loads(sig_path.read_text(encoding="utf-8")) if sig_path.exists() else {}
    need = [d for d in (set(tagged) | anc_ids) if d not in sig]
    if need:
        print(f"\n=== significance glosses: {len(need)} to write ===", flush=True)
        res = run_batch(client, sig_jobs(need, meta_full, tagged), budget, "sig")
        for cid, r in res.items():
            if r.get("sig"):
                sig[cid] = clip(r["sig"], 240)
        sig_path.write_text(json.dumps(sig, ensure_ascii=False), encoding="utf-8")

    # === 3b) long 3-part descriptions (does / connects / enables), cached ==
    desc_path = STATE_DIR / "desc.json"
    descs = json.loads(desc_path.read_text(encoding="utf-8")) if desc_path.exists() else {}
    union = set(tagged) | anc_ids
    need_d = [d for d in union if d not in descs]
    if need_d:
        print(f"\n=== descriptions: {len(need_d)} to write ===", flush=True)
        dmeta = load_meta_for(con, need_d)
        res = run_batch(client, desc_jobs(need_d, dmeta), budget, "desc")
        for cid, r in res.items():
            if r.get("does") and r.get("connects") and r.get("enables"):
                descs[cid] = {"does": clip(r["does"], DESC_CHARS),
                              "connects": clip(r["connects"], DESC_CHARS),
                              "enables": clip(r["enables"], DESC_CHARS)}
        desc_path.write_text(json.dumps(descs, ensure_ascii=False), encoding="utf-8")

    # === 4) future bridge + canonical anchor per tagged paper (cached) ====
    bridge_path = STATE_DIR / "bridge.json"
    bridges = json.loads(bridge_path.read_text(encoding="utf-8")) if bridge_path.exists() else {}
    todo = {d: tagged[d] for d in tagged if d not in bridges}
    if todo:
        print(f"\n=== future bridges + anchors: {len(todo)} to write ===", flush=True)
        res = run_batch(client, bridge_jobs(todo, future_paths, fmeta), budget, "bridge")
        for cid, r in res.items():
            bridges[cid] = {"bridge": clip(r.get("bridge") or "", 260),
                            "anchor": r.get("anchor") if r.get("anchor") in ANCHOR_BY_ID else None}
        bridge_path.write_text(json.dumps(bridges, ensure_ascii=False), encoding="utf-8")

    # === 5) assemble + write artifacts ====================================
    print("\n=== writing artifacts ===", flush=True)

    def anc_entry(c):
        m = meta_full[c["i"]]
        return {"i": c["i"], "t": m["t"], "y": m["y"], "u": m["u"], "v": m["v"],
                "sim": c["sim"], "sig": sig.get(c["i"], "")}

    lineage = {}
    for d, ch in chains.items():
        # ancestors oldest -> newest (parent last); UI shows anchor above these
        anc = [anc_entry(c) for c in reversed(ch)]
        anchor_id = (bridges.get(d) or {}).get("anchor")
        anchor = ANCHOR_BY_ID.get(anchor_id) if anchor_id else None
        lineage[d] = {"anc": anc, "anchor": anchor}
    (OUT_DIR / "lineage.json").write_text(
        json.dumps(lineage, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    paper_detail = {}
    for d in tagged:
        b = bridges.get(d) or {}
        paper_detail[d] = {"sig": sig.get(d, ""), "bridge": b.get("bridge", ""),
                           "anchor": b.get("anchor"), "future": future_paths.get(d)}
    (OUT_DIR / "paper_detail.json").write_text(
        json.dumps(paper_detail, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # one long-description file per paper — fetched on demand by the overlay
    DESC_DIR.mkdir(parents=True, exist_ok=True)
    for d, v in descs.items():
        (DESC_DIR / f"{d}.json").write_text(
            json.dumps(v, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # merge future facet into the explorer's two shared artifacts
    facets_file = OUT_DIR / "facets.json"
    facets = json.loads(facets_file.read_text(encoding="utf-8"))
    facets["facets"]["future"] = future_tree
    facets_file.write_text(json.dumps(facets, ensure_ascii=False), encoding="utf-8")

    tags_file = OUT_DIR / "paper_tags.json"
    ptags = json.loads(tags_file.read_text(encoding="utf-8"))
    for d in ptags:
        ptags[d]["future"] = future_paths.get(d)
    for d in tagged:  # in case the future pass saw a paper tags didn't
        ptags.setdefault(d, {})["future"] = future_paths.get(d)
    tags_file.write_text(json.dumps(ptags, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"\nDONE · total spend ${budget.spent:.2f}", flush=True)
    print(f"   lineage.json       {len(lineage)} papers", flush=True)
    print(f"   paper_detail.json  {len(paper_detail)} papers", flush=True)
    print(f"   desc/*.json        {len(descs)} papers", flush=True)
    print(f"   facets.json        + future facet", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

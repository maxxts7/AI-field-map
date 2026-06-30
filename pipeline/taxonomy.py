"""Hierarchical, multi-facet tagging of the corpus via Claude (Batch API).

A separate offline pass from the thematic-evolution pipeline. For each FACET
(a root lens — methodology, approach, threat, contribution) it builds a tree
TOP-DOWN by recursive division:

  node (papers) --Claude proposes 6-9 sub-tags--> children
                --Batch API tags each paper into one child (1 request/paper)-->
  any child with > CAP papers is split again, until leaves have <= CAP papers
  (or MAX_DEPTH / the budget guard stops it).

One request per paper (no cross-contamination), Haiku 4.5, structured outputs,
50%-off Batch API. A running cost tracker stops before exceeding --max-cost.
The API key is read from key.env and never printed. Heavy/LLM work is here only;
nothing ships to Netlify — artifacts land in public/data/taxonomy/.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY_FILE = REPO / "key.env"
DB_PATH = Path(__file__).resolve().parent / "corpus.db"
OUT_DIR = REPO / "public" / "data" / "taxonomy"
STATE_DIR = Path(__file__).resolve().parent / "data" / "raw" / "taxonomy"

MODEL = "claude-haiku-4-5"
CAP = 20            # max papers per leaf tag
MAX_DEPTH = 5       # hard safety cap on tree depth
SAMPLE_TITLES = 40  # representative titles shown to the splitter
ABSTRACT_CHARS = 1100

# Haiku 4.5: $1/M in, $5/M out. Batch = 50% off; sync proposals = full price.
P_IN, P_OUT = 1.0 / 1e6, 5.0 / 1e6

FACETS = {
    "methodology": {
        "title": "Methodology / lifecycle",
        "desc": "where in the model's lifecycle the paper's primary technical work acts",
        "seed": "",
        # Root level is FIXED to lifecycle stages (per the spec); Claude splits deeper.
        "root_children": [
            {"slug": "pretraining", "label": "Pretraining intervention",
             "description": "Acts during pretraining / base-model creation: pretraining data curation, pretraining objectives, base-model architecture."},
            {"slug": "training", "label": "Training intervention",
             "description": "Acts during the main supervised training run: training objectives, optimization, training-time defenses."},
            {"slug": "post-training", "label": "Post-training intervention",
             "description": "Post-training alignment: RLHF, DPO/preference optimization, SFT, fine-tuning, model editing, unlearning."},
            {"slug": "inference-time", "label": "Inference-time intervention",
             "description": "Acts at inference/decoding without changing weights: prompting, decoding control, steering, monitoring, guardrails, filtering (black-box and white-box)."},
            {"slug": "data-centric", "label": "Data-centric intervention",
             "description": "Operates on the data itself: dataset filtering, synthetic data, poisoning attacks/defenses, data attribution."},
            {"slug": "deployment-monitoring", "label": "Deployment & monitoring",
             "description": "Acts at deployment time: runtime monitoring, oversight, control protocols, incident response."},
            {"slug": "evaluation-only", "label": "Evaluation / analysis only",
             "description": "No intervention: measures, benchmarks, audits, or analyzes model behaviour."},
        ],
    },
    "approach": {
        "title": "Safety approach / agenda",
        "desc": "the AI-safety research agenda or approach the paper advances",
        "seed": ("Typical level-1 groups: AI alignment, AI control, interpretability, "
                 "evaluation & red-teaming, robustness, scalable oversight, governance & policy."),
    },
    "threat": {
        "title": "Threat / risk addressed",
        "desc": "the threat or risk the paper primarily addresses",
        "seed": ("Typical level-1 groups: deception & misalignment, misuse & dual-use, "
                 "jailbreaks & adversarial attacks, dangerous capabilities, loss of control, "
                 "privacy & data leakage, reliability & hallucination."),
    },
    "contribution": {
        "title": "Contribution type",
        "desc": "what kind of contribution the paper makes",
        "seed": ("Typical level-1 groups: method/technique, benchmark/dataset, "
                 "empirical analysis, theory/position, tool/system, survey."),
    },
}


# --- spend tracking (reporting only, no enforcement) ---------------------
class Budget:
    def __init__(self):
        self.spent = 0.0

    def add(self, in_tok: int, out_tok: int, batch: bool):
        mult = 0.5 if batch else 1.0
        self.spent += (in_tok * P_IN + out_tok * P_OUT) * mult


# --- helpers -------------------------------------------------------------
def load_key() -> None:
    import os

    key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key.startswith("sk-ant"):
        raise SystemExit("key.env does not contain an Anthropic key")
    os.environ["ANTHROPIC_API_KEY"] = key


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "tag"


def get_papers(con, where: str) -> dict[str, dict]:
    rows = con.execute(
        f"SELECT doc_id, title, COALESCE(body_text,''), CAST(date AS VARCHAR), source_layer "
        f"FROM documents WHERE {where}"
    ).fetchall()
    return {
        r[0]: {"title": r[1] or "", "abstract": r[2] or "", "date": r[3], "layer": r[4]}
        for r in rows
    }


def paper_text(p: dict) -> str:
    return f"TITLE: {p['title']}\n\nABSTRACT: {p['abstract'][:ABSTRACT_CHARS]}"


# --- Claude calls --------------------------------------------------------
def propose_children(client, facet: dict, node_label: str, node_path: str,
                     titles: list[str], is_root: bool, budget: Budget) -> list[dict]:
    seed = ("\n" + facet["seed"]) if is_root else ""
    system = (
        f"You are building a hierarchical taxonomy of AI-safety papers for the "
        f"'{facet['title']}' facet ({facet['desc']}).\n"
        f"Current node: {node_path}.\n"
        f"Propose 6 to 9 sub-groups that partition THIS node's papers at the next "
        f"level of granularity: mutually distinct, collectively covering the papers "
        f"shown, at a consistent level of specificity. Each sub-group needs a short "
        f"kebab-case slug, a human label, and a one-line description.{seed}"
    )
    user = "Representative paper titles in this node:\n" + "\n".join(f"- {t}" for t in titles)
    schema = {
        "type": "object",
        "properties": {"children": {"type": "array", "items": {
            "type": "object",
            "properties": {"slug": {"type": "string"}, "label": {"type": "string"},
                           "description": {"type": "string"}},
            "required": ["slug", "label", "description"], "additionalProperties": False}}},
        "required": ["children"], "additionalProperties": False,
    }
    msg = client.messages.create(
        model=MODEL, max_tokens=900, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    budget.add(msg.usage.input_tokens, msg.usage.output_tokens, batch=False)
    data = json.loads(msg.content[0].text)
    out, seen = [], set()
    for ch in data["children"]:
        s = slugify(ch["slug"])
        while s in seen:
            s += "-x"
        seen.add(s)
        out.append({"slug": s, "label": ch["label"][:60], "description": ch["description"][:200]})
    return out


def run_tag_batch(client, jobs: list[dict], budget: Budget) -> dict[str, str]:
    """jobs: [{cid, system, user, slugs}]. Returns {cid: chosen_slug}."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    reqs = []
    for j in jobs:
        schema = {"type": "object",
                  "properties": {"tag": {"type": "string", "enum": j["slugs"]}},
                  "required": ["tag"], "additionalProperties": False}
        reqs.append(Request(custom_id=j["cid"], params=MessageCreateParamsNonStreaming(
            model=MODEL, max_tokens=80, system=j["system"],
            messages=[{"role": "user", "content": j["user"]}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )))
    batch = client.messages.batches.create(requests=reqs)
    print(f"      batch {batch.id} ({len(reqs)} reqs) submitted", flush=True)
    while True:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        time.sleep(12)
    out: dict[str, str] = {}
    # Fall back to the job's OWN first option — never another node's slug, which
    # would land in a phantom bucket and silently drop the paper.
    fb = {j["cid"]: j["slugs"][0] for j in jobs}
    in_tok = out_tok = 0
    for r in client.messages.batches.results(batch.id):
        if r.result.type == "succeeded":
            m = r.result.message
            in_tok += m.usage.input_tokens
            out_tok += m.usage.output_tokens
            try:
                out[r.custom_id] = json.loads(m.content[0].text)["tag"]
            except Exception:  # noqa: BLE001
                out[r.custom_id] = fb[r.custom_id]
        else:
            out[r.custom_id] = fb[r.custom_id]
    budget.add(in_tok, out_tok, batch=True)
    print(f"      done: {b.request_counts.succeeded} ok / {b.request_counts.errored} err "
          f"· spent ${budget.spent:.2f}", flush=True)
    return out


# --- recursive build -----------------------------------------------------
def build_facet(client, fkey: str, papers: dict[str, dict], budget: Budget) -> dict:
    facet = FACETS[fkey]
    root = {"id": fkey, "slug": fkey, "label": facet["title"], "description": facet["desc"],
            "depth": 0, "papers": list(papers), "children": None}
    nodes = {fkey: root}
    frontier = [root]

    while frontier:
        to_split = [n for n in frontier if len(n["papers"]) > CAP and n["depth"] < MAX_DEPTH]
        for n in frontier:
            if n not in to_split:
                n["children"] = []  # leaf

        if not to_split:
            break
        level_papers = sum(len(n["papers"]) for n in to_split)
        print(f"   depth {to_split[0]['depth']+1}: splitting {len(to_split)} node(s), "
              f"{level_papers} papers", flush=True)
        # 1) propose children per node (sync); a facet may fix its root level
        for n in to_split:
            if n["depth"] == 0 and facet.get("root_children"):
                n["_children_defs"] = facet["root_children"]
                continue
            titles = [papers[d]["title"][:120] for d in n["papers"][:SAMPLE_TITLES]]
            n["_children_defs"] = propose_children(
                client, facet, n["label"], n["id"], titles, n["depth"] == 0, budget)
        # 2) one tagging batch across all splitting nodes
        jobs, idx = [], {}
        for n in to_split:
            defs = n["_children_defs"]
            opts = "\n".join(f"- {c['slug']}: {c['description']}" for c in defs)
            system = (f"Assign the paper to exactly one sub-group of '{n['label']}' "
                      f"in the {facet['title']} facet. Choose the single best fit.\n"
                      f"Sub-groups:\n{opts}")
            slugs = [c["slug"] for c in defs]
            for d in n["papers"]:
                cid = f"r{len(jobs)}"
                idx[cid] = (n, d)
                jobs.append({"cid": cid, "system": system,
                             "user": paper_text(papers[d]), "slugs": slugs})
        assign = run_tag_batch(client, jobs, budget)
        # 3) materialise children
        new_frontier = []
        for n in to_split:
            buckets: dict[str, list[str]] = {c["slug"]: [] for c in n["_children_defs"]}
            first_slug = next(iter(buckets))
            for cid, (nn, d) in idx.items():
                if nn is n:
                    slug = assign.get(cid, first_slug)
                    if slug not in buckets:  # out-of-vocab tag -> never drop the paper
                        slug = first_slug
                    buckets[slug].append(d)
            child_ids = []
            for cdef in n["_children_defs"]:
                docs = buckets.get(cdef["slug"], [])
                if not docs:
                    continue
                cid = f"{n['id']}/{cdef['slug']}"
                # no-progress guard: a child holding the whole parent can't be split further
                no_progress = len(docs) == len(n["papers"])
                node = {"id": cid, "slug": cdef["slug"], "label": cdef["label"],
                        "description": cdef["description"], "depth": n["depth"] + 1,
                        "papers": docs, "children": [] if no_progress else None}
                nodes[cid] = node
                child_ids.append(cid)
                if not no_progress:
                    new_frontier.append(node)
            n["children"] = child_ids
            del n["_children_defs"]
        frontier = new_frontier

    return nodes


def to_tree(nodes: dict, root_id: str) -> dict:
    n = nodes[root_id]
    out = {"id": n["id"], "slug": n["slug"], "label": n["label"],
           "description": n["description"], "depth": n["depth"], "count": len(n["papers"])}
    kids = n.get("children") or []
    if kids:
        out["children"] = [to_tree(nodes, k) for k in kids]
    else:
        out["leaf"] = True
    return out


def leaf_paths(nodes: dict, root_id: str) -> dict[str, list[str]]:
    """doc_id -> leaf node id (one per facet)."""
    out: dict[str, str] = {}

    def walk(nid):
        n = nodes[nid]
        kids = n.get("children") or []
        if not kids:
            for d in n["papers"]:
                out[d] = n["id"]
        else:
            for k in kids:
                walk(k)

    walk(root_id)
    return out


def main(argv=None) -> int:
    import duckdb

    p = argparse.ArgumentParser(description="Hierarchical multi-facet tagging via Claude")
    p.add_argument("--facets", nargs="+", default=list(FACETS), choices=list(FACETS))
    p.add_argument("--since", default="2026-01-01",
                   help="keep formal papers with date >= this (lab always kept)")
    p.add_argument("--limit", type=int, default=0, help="prototype: cap paper count")
    args = p.parse_args(argv)

    load_key()
    import anthropic

    client = anthropic.Anthropic()
    con = duckdb.connect(str(DB_PATH), read_only=True)
    where = (f"safety_relevant=TRUE AND (source_layer='lab_report' "
             f"OR (source_layer='formal' AND CAST(date AS VARCHAR) >= '{args.since}'))")
    papers = get_papers(con, where)
    if args.limit:
        papers = dict(list(papers.items())[: args.limit])
    print(f"corpus for tagging: {len(papers)} papers · facets={args.facets} · "
          f"cap<= {CAP}/leaf", flush=True)

    budget = Budget()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    facet_trees, all_paths = {}, {}
    for fkey in args.facets:
        state = STATE_DIR / f"{fkey}.json"
        if state.exists():
            print(f"\n=== facet '{fkey}': loading cached state ===", flush=True)
            saved = json.loads(state.read_text(encoding="utf-8"))
            facet_trees[fkey] = saved["tree"]
            all_paths[fkey] = saved["paths"]
            continue
        print(f"\n=== facet '{fkey}' === (spent so far ${budget.spent:.2f})", flush=True)
        nodes = build_facet(client, fkey, papers, budget)
        tree = to_tree(nodes, fkey)
        paths = leaf_paths(nodes, fkey)
        facet_trees[fkey] = tree
        all_paths[fkey] = paths
        state.write_text(json.dumps({"tree": tree, "paths": paths}), encoding="utf-8")
        print(f"   facet '{fkey}' done · {sum(1 for _ in _iter_leaves(tree))} leaves", flush=True)

    # per-paper tag set across facets
    per_paper = {}
    for d in papers:
        per_paper[d] = {f: all_paths.get(f, {}).get(d) for f in args.facets}

    (OUT_DIR / "facets.json").write_text(
        json.dumps({"facets": facet_trees, "n_papers": len(papers),
                    "cap": CAP, "since": args.since}, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "paper_tags.json").write_text(
        json.dumps(per_paper, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\nDONE · total spend ${budget.spent:.2f} · wrote {OUT_DIR}", flush=True)
    return 0


def _iter_leaves(tree):
    if tree.get("leaf"):
        yield tree
    for c in tree.get("children", []):
        yield from _iter_leaves(c)


if __name__ == "__main__":
    raise SystemExit(main())

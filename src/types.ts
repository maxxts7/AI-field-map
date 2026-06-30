// Data contract for the taxonomy explorer. Mirrors pipeline/taxonomy.py output
// in public/data/taxonomy/: facets.json, paper_tags.json, papers.json.

export type FacetKey =
  | "methodology"
  | "approach"
  | "threat"
  | "contribution"
  | "future";

/** One node in a facet's tag tree (facets.json). */
export interface TaxNode {
  id: string; // full path, e.g. "methodology/post-training/rlhf-dpo"
  slug: string;
  label: string;
  description: string;
  depth: number;
  count: number;
  leaf?: boolean;
  children?: TaxNode[];
}

export interface FacetsData {
  facets: Record<FacetKey, TaxNode>;
  n_papers: number;
  cap: number;
  since: string;
}

/** paper_tags.json: doc_id -> { facet: leaf-path }. */
export type PaperTags = Record<string, Record<FacetKey, string | null>>;

/** papers.json: doc_id -> compact metadata. */
export interface PaperMeta {
  t: string; // title
  u: string; // url
  d: string; // full date yyyy-mm-dd
  y: string; // year
  v: string; // venue / source
  l: "formal" | "lab_report";
}
export type Papers = Record<string, PaperMeta>;

export const FACET_ORDER: FacetKey[] = [
  "methodology",
  "approach",
  "threat",
  "contribution",
  "future",
];

export const FACET_LABEL: Record<FacetKey, string> = {
  methodology: "Methodology",
  approach: "Approach",
  threat: "Threat",
  contribution: "Contribution",
  future: "Future",
};

export const FACET_BLURB: Record<FacetKey, string> = {
  methodology: "where in the model lifecycle the work acts",
  approach: "the safety research agenda",
  threat: "the risk being addressed",
  contribution: "what kind of contribution it is",
  future: "the direction the work points toward, on the path to safe AI",
};

// --- per-paper lineage + future detail (lineage.json, paper_detail.json) ---

/** One antecedent in a lineage chain (oldest → newest in the array). */
export interface LineageAnc {
  i: string; // doc_id
  t: string; // title
  y: string; // year
  u: string; // url
  v: string; // source / venue
  sim: number; // cosine similarity to the step it precedes
  sig: string; // one-line significance gloss
}

/** A curated canonical work that a lineage bottoms out at. */
export interface Anchor {
  id: string;
  t: string; // title
  a: string; // authors
  y: string; // year
  u: string; // url
  sig: string; // significance
}

/** lineage.json: doc_id -> the paper's antecedent chain + canonical root. */
export interface LineageEntry {
  anc: LineageAnc[]; // oldest → newest (immediate parent last)
  anchor: Anchor | null;
}
export type Lineage = Record<string, LineageEntry>;

/** paper_detail.json: doc_id -> significance + forward bridge + routing. */
export interface PaperDetailMeta {
  sig: string; // what this paper itself established
  bridge: string; // forward link to its future direction
  anchor: string | null; // chosen canonical anchor id
  future: string | null; // future-facet leaf path
}
export type PaperDetails = Record<string, PaperDetailMeta>;

/** desc/<doc_id>.json: a long, three-part description, fetched on demand.
 * Exists for every paper shown anywhere (tagged papers + lineage antecedents). */
export interface PaperDescription {
  does: string; // what the paper itself does
  connects: string; // how it builds on prior work
  enables: string; // what it enables / points toward next
}

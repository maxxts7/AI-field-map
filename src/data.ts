// Loads the three taxonomy artifacts the explorer renders. All static JSON
// under public/data/taxonomy/ — no backend.
import type {
  FacetsData,
  Lineage,
  PaperDescription,
  PaperDetails,
  PaperTags,
  Papers,
} from "./types";

const BASE = "data/taxonomy";

async function getJSON<T>(name: string): Promise<T> {
  const res = await fetch(`${BASE}/${name}`);
  if (!res.ok) throw new Error(`Failed to load ${name} (${res.status})`);
  return res.json() as Promise<T>;
}

/** Optional artifact: resolve to a fallback if it hasn't been generated yet. */
async function getOptional<T>(name: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${BASE}/${name}`);
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    return fallback;
  }
}

export interface TaxonomyData {
  facets: FacetsData;
  tags: PaperTags;
  papers: Papers;
  lineage: Lineage;
  details: PaperDetails;
}

export async function loadTaxonomy(): Promise<TaxonomyData> {
  const [facets, tags, papers, lineage, details] = await Promise.all([
    getJSON<FacetsData>("facets.json"),
    getJSON<PaperTags>("paper_tags.json"),
    getJSON<Papers>("papers.json"),
    getOptional<Lineage>("lineage.json", {}),
    getOptional<PaperDetails>("paper_detail.json", {}),
  ]);
  return { facets, tags, papers, lineage, details };
}

// Per-paper long descriptions are large in aggregate (~one paragraph × 3 per
// paper), so they are fetched one file at a time when a paper is opened or an
// antecedent is expanded, and memoized. null = not generated yet / missing.
const descCache = new Map<string, PaperDescription | null>();

export async function loadDescription(docId: string): Promise<PaperDescription | null> {
  const hit = descCache.get(docId);
  if (hit !== undefined) return hit;
  let val: PaperDescription | null = null;
  try {
    const res = await fetch(`${BASE}/desc/${encodeURIComponent(docId)}.json`);
    if (res.ok) val = (await res.json()) as PaperDescription;
  } catch {
    val = null;
  }
  descCache.set(docId, val);
  return val;
}

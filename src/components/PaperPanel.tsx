import { useMemo } from "react";
import type { FacetKey, Papers, PaperTags } from "../types";
import { useOpenPaper } from "../paperDetail";

const CAP = 300;

/** Papers whose tag path in this lens is `nodeId` or sits under it. */
function papersUnder(
  nodeId: string,
  lens: FacetKey,
  tags: PaperTags,
): string[] {
  const out: string[] = [];
  for (const [doc, t] of Object.entries(tags)) {
    const p = t[lens];
    if (p && (p === nodeId || p.startsWith(nodeId + "/"))) out.push(doc);
  }
  return out;
}

export function PaperPanel({
  nodeId,
  nodeLabel,
  lens,
  tags,
  papers,
  query,
  onOpenPaper,
  emptyHint = "Click a tile to inspect its papers. Click again to zoom in; use the breadcrumb to zoom out.",
}: {
  nodeId: string | null;
  nodeLabel: string;
  lens: FacetKey;
  tags: PaperTags;
  papers: Papers;
  query: string;
  onOpenPaper?: (docId: string) => void;
  emptyHint?: string;
}) {
  const ctxOpen = useOpenPaper();
  const open = onOpenPaper ?? ctxOpen ?? undefined;
  const docs = useMemo(
    () => (nodeId ? papersUnder(nodeId, lens, tags) : []),
    [nodeId, lens, tags],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const items = docs
      .map((d) => ({ id: d, m: papers[d] }))
      .filter((x) => x.m && (!q || x.m.t.toLowerCase().includes(q)));
    items.sort((a, b) => (b.m.y || "").localeCompare(a.m.y || ""));
    return items;
  }, [docs, papers, query]);

  if (!nodeId) {
    return (
      <aside className="panel panel--empty">
        <svg className="panel__glyph" viewBox="0 0 64 40" aria-hidden="true">
          <line x1="10" y1="20" x2="30" y2="10" />
          <line x1="10" y1="20" x2="30" y2="30" />
          <line x1="30" y1="10" x2="52" y2="20" />
          <line x1="30" y1="30" x2="52" y2="20" />
          <circle cx="10" cy="20" r="3.5" />
          <circle cx="30" cy="10" r="3.5" />
          <circle cx="30" cy="30" r="3.5" />
          <circle className="panel__glyph-on" cx="52" cy="20" r="4.5" />
        </svg>
        <p>{emptyHint}</p>
      </aside>
    );
  }

  return (
    <aside className="panel">
      <div className="panel__head">
        <div className="panel__crumb">{nodeId.split("/").slice(1).join("  ›  ")}</div>
        <h2>{nodeLabel}</h2>
        <div className="panel__count">
          {rows.length.toLocaleString()}
          {query ? ` of ${docs.length.toLocaleString()}` : ""} papers
        </div>
      </div>
      <ul className="papers">
        {rows.slice(0, CAP).map(({ id, m }) => (
          <li
            key={id}
            className={open ? "paper paper--click" : "paper"}
            onClick={open ? () => open(id) : undefined}
            role={open ? "button" : undefined}
            tabIndex={open ? 0 : undefined}
            onKeyDown={
              open ? (e) => (e.key === "Enter" || e.key === " ") && open(id) : undefined
            }
          >
            <span className={`dot dot--${m.l === "lab_report" ? "lab" : "formal"}`} />
            <div className="paper__body">
              {open ? (
                <span className="paper__title">{m.t}</span>
              ) : m.u ? (
                <a href={m.u} target="_blank" rel="noreferrer" className="paper__title">
                  {m.t}
                </a>
              ) : (
                <span className="paper__title">{m.t}</span>
              )}
              <div className="paper__meta">
                {m.y}
                {m.v ? ` · ${m.v}` : ""}
                {open && <span className="paper__cue"> · lineage ↗</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {rows.length > CAP && (
        <div className="panel__more">+{(rows.length - CAP).toLocaleString()} more — refine with search</div>
      )}
    </aside>
  );
}

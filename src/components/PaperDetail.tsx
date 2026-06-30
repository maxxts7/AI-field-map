import { useEffect, useMemo, useState, type ReactNode } from "react";
import { loadDescription } from "../data";
import type {
  Lineage,
  LineageAnc,
  PaperDescription,
  PaperDetails,
  Papers,
  TaxNode,
} from "../types";

/** Flatten a facet tree into id -> node for breadcrumb / sibling lookups. */
function indexTree(root?: TaxNode): Map<string, TaxNode> {
  const m = new Map<string, TaxNode>();
  const walk = (n: TaxNode) => {
    m.set(n.id, n);
    n.children?.forEach(walk);
  };
  if (root) walk(root);
  return m;
}

/** The three-part long description: what it does, how it connects, what it enables. */
function DescBlock({ d }: { d: PaperDescription }) {
  return (
    <div className="desc">
      <div className="desc__part">
        <div className="desc__label">What it does</div>
        <p className="desc__text">{d.does}</p>
      </div>
      <div className="desc__part">
        <div className="desc__label">How it connects to earlier work</div>
        <p className="desc__text">{d.connects}</p>
      </div>
      <div className="desc__part">
        <div className="desc__label">What it enables next</div>
        <p className="desc__text">{d.enables}</p>
      </div>
    </div>
  );
}

/** An overlay section with a clickable header that collapses its body. */
function CollapsibleBlock({
  title,
  sub,
  defaultOpen = true,
  children,
}: {
  title: string;
  sub?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="block">
      <h3
        className="block__h block__h--toggle"
        role="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="block__chev" aria-hidden="true">{open ? "−" : "+"}</span>
        {title}
        {sub && (
          <>
            {" "}
            <span className="block__sub">{sub}</span>
          </>
        )}
      </h3>
      {open && children}
    </section>
  );
}

/** One antecedent in the lineage timeline; its long description loads on expand. */
function AncItem({ a }: { a: LineageAnc }) {
  const [open, setOpen] = useState(false);
  const [desc, setDesc] = useState<PaperDescription | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "done">("idle");

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && state === "idle") {
      setState("loading");
      loadDescription(a.i).then((d) => {
        setDesc(d);
        setState("done");
      });
    }
  };

  return (
    <li className="tl">
      <div className="tl__year">{a.y}</div>
      <div className="tl__body">
        <a className="tl__title" href={a.u} target="_blank" rel="noreferrer">
          {a.t}
        </a>
        {a.sig && <div className="tl__sig">{a.sig}</div>}
        <div className="tl__foot">
          {a.v}
          {a.sim ? ` · ${Math.round(a.sim * 100)}% related` : ""}
        </div>
        <button className="tl__more" onClick={toggle} aria-expanded={open}>
          {open ? "− hide" : "＋ how it connects / what it enables"}
        </button>
        {open &&
          (state === "loading" ? (
            <div className="desc__loading">Loading…</div>
          ) : desc ? (
            <DescBlock d={desc} />
          ) : (
            <div className="desc__loading">No extended description yet.</div>
          ))}
      </div>
    </li>
  );
}

export function PaperDetail({
  docId,
  papers,
  lineage,
  details,
  futureRoot,
  onClose,
}: {
  docId: string;
  papers: Papers;
  lineage: Lineage;
  details: PaperDetails;
  futureRoot?: TaxNode;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The opened paper's own long description, fetched on demand.
  const [desc, setDesc] = useState<PaperDescription | null>(null);
  useEffect(() => {
    let alive = true;
    setDesc(null);
    loadDescription(docId).then((d) => alive && setDesc(d));
    return () => {
      alive = false;
    };
  }, [docId]);

  const index = useMemo(() => indexTree(futureRoot), [futureRoot]);

  const m = papers[docId];
  const le = lineage[docId];
  const det = details[docId];

  // future-direction breadcrumb + adjacent leaves
  const fut = useMemo(() => {
    const path = det?.future;
    if (!path) return null;
    const segs = path.split("/");
    const crumbs = segs.slice(1).map((_, k) => {
      const id = segs.slice(0, k + 2).join("/");
      return index.get(id)?.label ?? segs[k + 1];
    });
    const leaf = index.get(path);
    const parentId = segs.slice(0, -1).join("/");
    const siblings = (index.get(parentId)?.children ?? []).filter((c) => c.id !== path);
    return { crumbs, leaf, siblings };
  }, [det, index]);

  if (!m) return null;
  const anc = le?.anc ?? [];
  const anchor = le?.anchor ?? null;
  const hasLineage = anchor || anc.length > 0;

  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <button className="sheet__close" onClick={onClose} aria-label="Close">
          ×
        </button>

        <header className="sheet__head">
          <div className="sheet__kicker">Paper</div>
          <h2 className="sheet__title">{m.t}</h2>
          <div className="sheet__meta">
            <span className={`dot dot--${m.l === "lab_report" ? "lab" : "formal"}`} />
            {m.y}
            {m.v ? ` · ${m.v}` : ""}
            {m.u && (
              <>
                {" · "}
                <a href={m.u} target="_blank" rel="noreferrer">
                  open original ↗
                </a>
              </>
            )}
          </div>
          {det?.sig && <p className="sheet__lead">{det.sig}</p>}
        </header>

        {desc && (
          <CollapsibleBlock
            title="About this work"
            sub="— what it does, builds on, and enables"
            defaultOpen={false}
          >
            <DescBlock d={desc} />
          </CollapsibleBlock>
        )}

        <CollapsibleBlock title="Lineage" sub="— the work that enabled this, oldest first">
          {!hasLineage ? (
            <p className="block__empty">
              Lineage hasn't been generated yet. Run <code>python -m pipeline.lineage_future</code>.
            </p>
          ) : (
            <ol className="timeline">
              {anchor && (
                <li className="tl tl--canon">
                  <div className="tl__year">{anchor.y}</div>
                  <div className="tl__body">
                    <span className="tl__badge">canonical</span>
                    <a className="tl__title" href={anchor.u} target="_blank" rel="noreferrer">
                      {anchor.t}
                    </a>
                    <div className="tl__sig">{anchor.sig}</div>
                    <div className="tl__foot">{anchor.a}</div>
                  </div>
                </li>
              )}
              {anc.map((a) => (
                <AncItem key={a.i} a={a} />
              ))}
              <li className="tl tl--self">
                <div className="tl__year">{m.y}</div>
                <div className="tl__body">
                  <span className="tl__badge tl__badge--now">this paper</span>
                  <span className="tl__title">{m.t}</span>
                </div>
              </li>
            </ol>
          )}
        </CollapsibleBlock>

        <CollapsibleBlock title="Future direction" sub="— where this line of work points">
          {!fut ? (
            <p className="block__empty">No future direction assigned.</p>
          ) : (
            <div className="fut">
              <div className="fut__crumb">
                {fut.crumbs.map((c, i) => (
                  <span key={i}>
                    {i > 0 && <span className="fut__sep"> › </span>}
                    <span className={i === fut.crumbs.length - 1 ? "fut__leaf" : undefined}>{c}</span>
                  </span>
                ))}
              </div>
              {fut.leaf?.description && <p className="fut__desc">{fut.leaf.description}</p>}
              {det?.bridge && <p className="fut__bridge">↗ {det.bridge}</p>}
              {fut.siblings.length > 0 && (
                <div className="fut__sibs">
                  <span className="fut__sibs-label">Adjacent directions</span>
                  {fut.siblings.slice(0, 6).map((s) => (
                    <span className="chip" key={s.id}>
                      {s.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </CollapsibleBlock>
      </div>
    </div>
  );
}

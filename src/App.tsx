import { useEffect, useMemo, useState } from "react";
import { loadTaxonomy, type TaxonomyData } from "./data";
import {
  FACET_ORDER,
  FACET_LABEL,
  FACET_BLURB,
  type FacetKey,
  type TaxNode,
} from "./types";
import { PaperDetail } from "./components/PaperDetail";
import { Trends } from "./components/Trends";
import { Streamgraph } from "./components/Streamgraph";
import { Help } from "./components/Help";
import { ComingSoon } from "./components/ComingSoon";
import { OpenPaperContext } from "./paperDetail";

function countLeaves(n: TaxNode): number {
  if (!n.children || !n.children.length) return 1;
  return n.children.reduce((s, c) => s + countLeaves(c), 0);
}

export default function App() {
  const [data, setData] = useState<TaxonomyData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lens, setLens] = useState<FacetKey>("methodology");
  const [mode, setMode] = useState<"evolution" | "trends">("evolution");
  const [openPaper, setOpenPaper] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const [showComingSoon, setShowComingSoon] = useState(false);

  useEffect(() => {
    loadTaxonomy().then(setData).catch((e) => setError(String(e)));
  }, []);

  // Reset the open paper when switching lens.
  useEffect(() => {
    setOpenPaper(null);
  }, [lens]);

  const root = data?.facets.facets[lens];
  const leaves = useMemo(() => (root ? countLeaves(root) : 0), [root]);

  if (error) {
    return (
      <div className="state state--error">
        <h2>Couldn't load the taxonomy</h2>
        <p>{error}</p>
        <p className="state__hint">
          Generate it first: <code>python pipeline/taxonomy.py</code>, then reload.
        </p>
      </div>
    );
  }
  if (!data || !root) {
    return <div className="state">Loading taxonomy…</div>;
  }

  const { n_papers, since } = data.facets;

  return (
    <OpenPaperContext.Provider value={setOpenPaper}>
    <div className="app">
      <header className="topbar">
        <div className="topbar__title">
          <div className="topbar__kicker">Interactive field map</div>
          <h1>AI Safety · Research Explorer</h1>
          <p className="lede">
            A living map of the field — <b>{n_papers.toLocaleString()}</b> recent papers,
            read and sorted by Claude across <b>{FACET_ORDER.length}</b> lenses, each traced
            back to the work it builds on.
          </p>
        </div>
        <div className="topbar__actions">
          <nav className="tabs">
            {FACET_ORDER.map((f) => (
              <button
                key={f}
                className={f === lens ? "tab tab--on" : "tab"}
                onClick={() => setLens(f)}
              >
                {FACET_LABEL[f]}
              </button>
            ))}
            <button className="tab tab--ghost" onClick={() => setShowComingSoon(true)}>
              ＋ Your map
            </button>
          </nav>
          <button
            className="help-btn"
            onClick={() => setShowHelp(true)}
            aria-label="How to use this explorer"
            title="How to use this explorer"
          >
            ?
          </button>
        </div>
      </header>

      <div className="lensbar">
        <span className="lensbar__blurb">
          <b>{FACET_LABEL[lens]}</b> — {FACET_BLURB[lens]} · {leaves} sub-topics
        </span>
        <div className="lensbar__right">
          <div className="seg">
            <button
              className={mode === "evolution" ? "seg__b seg__b--on" : "seg__b"}
              onClick={() => setMode("evolution")}
            >
              Evolution
            </button>
            <button
              className={mode === "trends" ? "seg__b seg__b--on" : "seg__b"}
              onClick={() => setMode("trends")}
            >
              Emerging
            </button>
          </div>
        </div>
      </div>

      {mode === "evolution" ? (
        <main className="main main--field">
          <Streamgraph key={lens} root={root} lens={lens} tags={data.tags} papers={data.papers} />
        </main>
      ) : (
        <main className="main main--trends">
          <Trends key={lens} root={root} lens={lens} tags={data.tags} papers={data.papers} accent="#ff9d4d" />
        </main>
      )}

      <footer className="foot">
        Formal arXiv papers since {since.slice(0, 4)}, alongside lab reports · tags and lineage
        assigned by Claude (Haiku 4.5) · select a band, then a paper, to follow its lineage and
        where the work points next
      </footer>
    </div>
    {openPaper && (
      <PaperDetail
        docId={openPaper}
        papers={data.papers}
        lineage={data.lineage}
        details={data.details}
        futureRoot={data.facets.facets.future}
        onClose={() => setOpenPaper(null)}
      />
    )}
    {showHelp && <Help onClose={() => setShowHelp(false)} />}
    {showComingSoon && <ComingSoon onClose={() => setShowComingSoon(false)} />}
    </OpenPaperContext.Provider>
  );
}

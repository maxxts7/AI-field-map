import { useEffect, useMemo, useRef, useState } from "react";
import {
  FACET_ORDER,
  type FacetKey,
  type Papers,
  type PaperTags,
  type TaxNode,
} from "../types";
import { useOpenPaper } from "../paperDetail";

type Frame = "month" | "year" | "all";
const FRAMES: { key: Frame; label: string }[] = [
  { key: "month", label: "This month" },
  { key: "year", label: "This year" },
  { key: "all", label: "All time" },
];

const UP = "#2f8f5b", DOWN = "#c0603a", FLAT = "#8a95a3";

// --- helpers -------------------------------------------------------------
function findNode(n: TaxNode, id: string): TaxNode | null {
  if (n.id === id) return n;
  for (const c of n.children ?? []) { const r = findNode(c, id); if (r) return r; }
  return null;
}
function docsUnder(id: string, lens: FacetKey, tags: PaperTags): string[] {
  const out: string[] = [];
  for (const [doc, t] of Object.entries(tags)) {
    const p = t[lens];
    if (p && (p === id || p.startsWith(id + "/"))) out.push(doc);
  }
  return out;
}
function monthsRange(end: string, count: number): string[] {
  let [y, m] = end.split("-").map(Number);
  const out: string[] = [];
  for (let i = 0; i < count; i++) { out.unshift(`${y}-${String(m).padStart(2, "0")}`); m--; if (m < 1) { m = 12; y--; } }
  return out;
}
const top1 = (path: string) => path.split("/")[1] ?? "";
function median(xs: number[]): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

/** Centrality = normalised entropy of a tag's co-occurring top-level tags in
 *  the OTHER three lenses. Low = isolated (always pairs with the same things);
 *  high = connected/transversal. `hmax` normalises across the scope. */
function centrality(docs: string[], lens: FacetKey, tags: PaperTags, hmax: number): number {
  const others = FACET_ORDER.filter((f) => f !== lens);
  const freq: Record<string, number> = {};
  let tot = 0;
  for (const d of docs) {
    const t = tags[d]; if (!t) continue;
    for (const f of others) {
      const p = t[f]; if (!p) continue;
      const k = f + ":" + top1(p);
      freq[k] = (freq[k] ?? 0) + 1; tot++;
    }
  }
  if (!tot || hmax <= 0) return 0;
  let H = 0;
  for (const k in freq) { const p = freq[k] / tot; H -= p * Math.log(p); }
  return Math.min(1, H / hmax);
}

function useSize() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 820, h: 540 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((es) => {
      const r = es[0].contentRect;
      if (r.width > 0 && r.height > 0) setSize({ w: r.width, h: r.height });
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return { ref, size };
}

interface Dir {
  node: TaxNode;
  count: number;
  share: number;       // window share of scope
  cx: number;          // centrality 0..1
  trend: number;       // Δ share (fraction)
  series: number[];    // count per period
  shareSeries: number[];
  trail: number[];     // share over the last few periods (comet tail; x fixed)
}

export function FieldMap({
  root, lens, tags, papers,
}: {
  root: TaxNode; lens: FacetKey; tags: PaperTags; papers: Papers;
}) {
  const [scopeId, setScopeId] = useState(root.id);
  const [frame, setFrame] = useState<Frame>("year");
  const [picked, setPicked] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const { ref, size } = useSize();

  const scope = useMemo(() => findNode(root, scopeId) ?? root, [root, scopeId]);

  const latestMonth = useMemo(() => {
    let mx = "";
    for (const p of Object.values(papers)) if (p.l === "formal" && p.d.slice(0, 7) > mx) mx = p.d.slice(0, 7);
    return mx || "2026-06";
  }, [papers]);

  const periods = useMemo(() => {
    if (frame === "month") return monthsRange(latestMonth, 6);
    if (frame === "year") return monthsRange(latestMonth, Number(latestMonth.split("-")[1]));
    const ys = new Set<string>();
    for (const p of Object.values(papers)) if (p.y) ys.add(p.y);
    return [...ys].sort();
  }, [frame, latestMonth, papers]);
  const gran: "month" | "year" = frame === "all" ? "year" : "month";
  const bucket = (d: string) => (gran === "year" ? d.slice(0, 4) : d.slice(0, 7));

  const dirs = useMemo<Dir[]>(() => {
    const kids = scope.children?.length ? scope.children : [scope];
    const pset = new Set(periods);
    const recentN = gran === "month" ? 2 : 1;
    // per-child docs + per-period buckets
    const docsByKid = kids.map((c) => ({ node: c, docs: docsUnder(c.id, lens, tags) }));
    // scope total per period
    const T = periods.map(() => 0);
    const childSeries = docsByKid.map(({ docs }) => {
      const s = periods.map(() => 0);
      for (const d of docs) {
        const dt = papers[d]?.d; if (!dt) continue;
        const i = periods.indexOf(bucket(dt));
        if (i >= 0) { s[i]++; T[i]++; }
      }
      return s;
    });
    const Tsum = T.reduce((a, b) => a + b, 0);
    // entropy normaliser over the whole scope's co-tags
    const others = FACET_ORDER.filter((f) => f !== lens);
    const universe = new Set<string>();
    for (const { docs } of docsByKid)
      for (const d of docs) { const t = tags[d]; if (!t) continue; for (const f of others) { const p = t[f]; if (p) universe.add(f + ":" + top1(p)); } }
    const hmax = Math.log(Math.max(2, universe.size));

    const sumAt = (a: number[], idx: number[]) => idx.reduce((s, i) => s + a[i], 0);
    const lateIdx = [...periods.keys()].slice(periods.length - recentN);
    const earlyIdx = [...periods.keys()].slice(0, periods.length - recentN);

    return docsByKid.map(({ node, docs }, ci) => {
      const series = childSeries[ci];
      const winDocs = docs.filter((d) => { const dt = papers[d]?.d; return dt && pset.has(bucket(dt)); });
      const count = winDocs.length;
      const share = Tsum ? count / Tsum : 0;
      const shareSeries = periods.map((_, i) => (T[i] ? series[i] / T[i] : 0));
      const eT = sumAt(T, earlyIdx), lT = sumAt(T, lateIdx);
      const eS = eT ? sumAt(series, earlyIdx) / eT : 0;
      const lS = lT ? sumAt(series, lateIdx) / lT : 0;
      const trend = eT && lT ? lS - eS : 0;
      const cx = centrality(winDocs, lens, tags, hmax);
      // comet tail = share over the last few periods (x stays fixed = the tag's
      // centrality; per-period centrality on a handful of papers is too noisy).
      const trail = shareSeries.slice(Math.max(0, shareSeries.length - 4));
      return { node, count, share, cx, trend, series, shareSeries, trail };
    }).filter((d) => d.count > 0);
  }, [scope, periods, lens, tags, papers, gran]);

  // --- geometry ---
  const M = { t: 26, r: 26, b: 38, l: 30 };
  const pw = Math.max(40, size.w - M.l - M.r);
  const ph = Math.max(40, size.h - M.t - M.b);
  const yMax = Math.max(0.06, ...dirs.map((d) => d.share)) * 1.12;
  const sx = (c: number) => M.l + c * pw;
  const sy = (s: number) => M.t + (1 - s / yMax) * ph;
  // spread centrality across the view's range so relative isolation is visible
  const cxs = dirs.map((d) => d.cx);
  const cMin = cxs.length ? Math.min(...cxs) : 0;
  const cMax = cxs.length ? Math.max(...cxs) : 1;
  const nx = (c: number) => 0.08 + (cMax > cMin ? (c - cMin) / (cMax - cMin) : 0.5) * 0.84;
  const rOf = (n: number) => Math.max(5, Math.min(38, Math.sqrt(n) * 3.0));
  const colorOf = (t: number) => (t > 0.005 ? UP : t < -0.005 ? DOWN : FLAT);
  const medX = median(dirs.map((d) => nx(d.cx)));
  const medY = median(dirs.map((d) => d.share));

  const crumb = scope.id.split("/");
  const sel = picked ?? hover;

  return (
    <div className="field">
      <div className="field__controls">
        <div className="crumbs">
          {crumb.map((part, i) => {
            const id = crumb.slice(0, i + 1).join("/");
            const node = findNode(root, id);
            const last = i === crumb.length - 1;
            return (
              <span key={id}>
                {i > 0 && <span className="crumbs__sep">›</span>}
                <button className={last ? "crumb crumb--on" : "crumb"} onClick={() => { setScopeId(id); setPicked(null); }}>
                  {i === 0 ? "All" : node?.label ?? part}
                </button>
              </span>
            );
          })}
        </div>
        <div className="seg">
          {FRAMES.map((f) => (
            <button key={f.key} className={frame === f.key ? "seg__b seg__b--on" : "seg__b"} onClick={() => setFrame(f.key)}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="field__body">
        <div className="field__plot" ref={ref}>
          <svg width={size.w} height={size.h} className="fmap">
            {/* quadrant wash + dividers */}
            <rect x={sx(medX)} y={M.t} width={M.l + pw - sx(medX)} height={sy(medY) - M.t} fill="#3b82c4" opacity="0.035" />
            <rect x={M.l} y={M.t} width={sx(medX) - M.l} height={sy(medY) - M.t} fill="#7c6bd0" opacity="0.035" />
            <line x1={sx(medX)} y1={M.t} x2={sx(medX)} y2={M.t + ph} stroke="#e6e9ee" strokeDasharray="3 4" />
            <line x1={M.l} y1={sy(medY)} x2={M.l + pw} y2={sy(medY)} stroke="#e6e9ee" strokeDasharray="3 4" />

            {/* axis captions */}
            <text x={M.l} y={M.t + ph + 26} className="fmap__axis">isolated</text>
            <text x={M.l + pw} y={M.t + ph + 26} className="fmap__axis" textAnchor="end">connected →</text>
            <text x={M.l - 6} y={M.t + 4} className="fmap__axis" transform={`rotate(-90 ${M.l - 6} ${M.t + 4})`} textAnchor="end">mainstream</text>
            <text x={M.l - 6} y={M.t + ph} className="fmap__axis" transform={`rotate(-90 ${M.l - 6} ${M.t + ph})`}>niche</text>

            {/* comet trails (tail = earlier share, head = now) */}
            {dirs.map((d) => {
              const bx = sx(nx(d.cx));
              const k = d.trail.length;
              const pts = d.trail.map((s, i) => `${(bx - (k - 1 - i) * 7).toFixed(1)},${sy(s).toFixed(1)}`).join(" ");
              return (
                <polyline
                  key={"tr" + d.node.id}
                  points={pts}
                  fill="none"
                  stroke={colorOf(d.trend)}
                  strokeWidth={sel === d.node.id ? 2.6 : 1.5}
                  strokeLinecap="round"
                  opacity={sel && sel !== d.node.id ? 0.1 : 0.42}
                />
              );
            })}

            {/* bubbles */}
            {dirs.map((d) => {
              const cx = sx(nx(d.cx)), cy = sy(d.share), r = rOf(d.count);
              const dim = sel && sel !== d.node.id;
              return (
                <g
                  key={d.node.id}
                  className="fmap__node"
                  onMouseEnter={() => setHover(d.node.id)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => ((d.node.children?.length ?? 0) ? setScopeId(d.node.id) : setPicked(d.node.id))}
                >
                  <circle cx={cx} cy={cy} r={r} fill={colorOf(d.trend)} fillOpacity={dim ? 0.18 : 0.62}
                    stroke="#fff" strokeWidth="1.5" />
                  {(r > 13 || sel === d.node.id) && (
                    <text x={cx} y={cy + 0.5} textAnchor="middle" className="fmap__blabel" opacity={dim ? 0.3 : 1}>
                      {d.node.label.length > 22 ? d.node.label.slice(0, 21) + "…" : d.node.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
        </div>

        <aside className="panel field__panel">
          {sel ? (
            <FlowDetail dir={dirs.find((d) => d.node.id === sel)!} periods={periods} gran={gran} />
          ) : (
            <div className="field__legend">
              <p>Each bubble is a research direction. <b>Right</b> = connects across the field, <b>left</b> = isolated niche. <b>Up</b> = large share, <b>down</b> = small. <b style={{ color: UP }}>Green</b> rising, <b style={{ color: DOWN }}>red</b> declining; the trail shows where it came from.</p>
              <p className="field__legend-hint">Hover a bubble for its flow over time. Click to drill into its sub-directions.</p>
            </div>
          )}
          <PaperList
            id={sel ?? scope.id}
            lens={lens} tags={tags} papers={papers}
            periods={periods} gran={gran}
          />
        </aside>
      </div>
    </div>
  );
}

// --- the per-direction flow (mini stacked area of its children over time) ---
function FlowDetail({ dir, periods, gran }: { dir: Dir; periods: string[]; gran: "month" | "year" }) {
  const w = 340, h = 96, n = periods.length;
  const max = Math.max(1, ...dir.series);
  const pts = dir.series.map((v, i) => `${(n === 1 ? w : (i / (n - 1)) * w).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`);
  const area = `0,${h} ${pts.join(" ")} ${w},${h}`;
  const fmt = (p: string) => (gran === "year" ? p : p.slice(2).replace("-", "/"));
  return (
    <div className="flow">
      <div className="panel__crumb">{dir.node.id.split("/").slice(1, -1).join("  ›  ") || "lifecycle"}</div>
      <h2>{dir.node.label}</h2>
      <div className="flow__stats">
        <span className="flow__share">{Math.round(dir.share * 100)}%</span>
        <span className={`flow__delta ${dir.trend > 0.005 ? "up" : dir.trend < -0.005 ? "down" : ""}`}>
          {dir.trend > 0.005 ? `▲ +${Math.round(dir.trend * 100)}pp` : dir.trend < -0.005 ? `▼ ${Math.round(dir.trend * 100)}pp` : "→ steady"}
        </span>
        <span className="flow__count">{dir.count} papers</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="flow__svg">
        <polygon points={area} fill="#2f6fae" opacity="0.12" />
        <polyline points={pts.join(" ")} fill="none" stroke="#2f6fae" strokeWidth="1.8" />
      </svg>
      <div className="flow__axis">
        <span>{fmt(periods[0])}</span>
        <span>{fmt(periods[n - 1])}</span>
      </div>
    </div>
  );
}

function PaperList({ id, lens, tags, papers, periods, gran }: {
  id: string; lens: FacetKey; tags: PaperTags; papers: Papers; periods: string[]; gran: "month" | "year";
}) {
  const open = useOpenPaper();
  const bucket = (d: string) => (gran === "year" ? d.slice(0, 4) : d.slice(0, 7));
  const rows = useMemo(() => {
    const pset = new Set(periods);
    return docsUnder(id, lens, tags)
      .filter((d) => papers[d] && pset.has(bucket(papers[d].d)))
      .map((d) => ({ id: d, m: papers[d] }))
      .sort((a, b) => b.m.d.localeCompare(a.m.d));
  }, [id, lens, tags, papers, periods, gran]);
  return (
    <ul className="papers papers--flow">
      {rows.slice(0, 120).map(({ id, m }) => (
        <li
          key={id}
          className={open ? "paper paper--click" : "paper"}
          onClick={open ? () => open(id) : undefined}
          role={open ? "button" : undefined}
          tabIndex={open ? 0 : undefined}
          onKeyDown={open ? (e) => (e.key === "Enter" || e.key === " ") && open(id) : undefined}
        >
          <span className={`dot dot--${m.l === "lab_report" ? "lab" : "formal"}`} />
          <div className="paper__body">
            {open ? (
              <span className="paper__title">{m.t}</span>
            ) : m.u ? (
              <a href={m.u} target="_blank" rel="noreferrer" className="paper__title">{m.t}</a>
            ) : (
              <span className="paper__title">{m.t}</span>
            )}
            <div className="paper__meta">{m.d}{m.v ? ` · ${m.v}` : ""}{open && <span className="paper__cue"> · lineage ↗</span>}</div>
          </div>
        </li>
      ))}
    </ul>
  );
}

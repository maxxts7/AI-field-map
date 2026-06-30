import { useMemo, useState } from "react";
import type { FacetKey, Papers, PaperTags, TaxNode } from "../types";
import { useOpenPaper } from "../paperDetail";

type Frame = "month" | "year" | "all";
type Sort = "rising" | "top";

const FRAMES: { key: Frame; label: string }[] = [
  { key: "month", label: "This month" },
  { key: "year", label: "This year" },
  { key: "all", label: "All time" },
];

// --- tree + date helpers -------------------------------------------------
function findNode(n: TaxNode, id: string): TaxNode | null {
  if (n.id === id) return n;
  for (const c of n.children ?? []) {
    const r = findNode(c, id);
    if (r) return r;
  }
  return null;
}

function docsUnder(nodeId: string, lens: FacetKey, tags: PaperTags): string[] {
  const out: string[] = [];
  for (const [doc, t] of Object.entries(tags)) {
    const p = t[lens];
    if (p && (p === nodeId || p.startsWith(nodeId + "/"))) out.push(doc);
  }
  return out;
}

function monthsRange(end: string, count: number): string[] {
  let [y, m] = end.split("-").map(Number);
  const out: string[] = [];
  for (let i = 0; i < count; i++) {
    out.unshift(`${y}-${String(m).padStart(2, "0")}`);
    m--;
    if (m < 1) { m = 12; y--; }
  }
  return out;
}

function Sparkline({ series, color }: { series: number[]; color: string }) {
  const w = 96, h = 26, max = Math.max(1, ...series);
  const n = series.length;
  const pts = series.map((v, i) => {
    const x = n === 1 ? w : (i / (n - 1)) * w;
    const y = h - 2 - (v / max) * (h - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const area = `0,${h} ${pts.join(" ")} ${w},${h}`;
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polygon points={area} fill={color} opacity="0.13" />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.6" />
      {series.length > 0 && (
        <circle
          cx={n === 1 ? w : w}
          cy={h - 2 - (series[n - 1] / max) * (h - 4)}
          r="2.2"
          fill={color}
        />
      )}
    </svg>
  );
}

export function Trends({
  root,
  lens,
  tags,
  papers,
  accent,
}: {
  root: TaxNode;
  lens: FacetKey;
  tags: PaperTags;
  papers: Papers;
  accent: string;
}) {
  const open = useOpenPaper();
  const [scopeId, setScopeId] = useState(root.id);
  const [frame, setFrame] = useState<Frame>("year");
  const [sort, setSort] = useState<Sort>("rising");
  const [metric, setMetric] = useState<"share" | "count">("share");
  const [picked, setPicked] = useState<string | null>(null);

  // scope resets when lens changes (root.id changes)
  const scope = useMemo(() => findNode(root, scopeId) ?? root, [root, scopeId]);

  // Anchor the monthly window to the latest FORMAL month — lab papers with a
  // year-only date were fallback-stamped YYYY-07-01, a fake month that would
  // otherwise hijack "this month". (They still count in the yearly "all" view.)
  const latestMonth = useMemo(() => {
    let mx = "";
    for (const p of Object.values(papers))
      if (p.l === "formal" && p.d.slice(0, 7) > mx) mx = p.d.slice(0, 7);
    return mx || "2026-06";
  }, [papers]);

  const periods = useMemo(() => {
    if (frame === "month") return monthsRange(latestMonth, 6);
    if (frame === "year") {
      const m = Number(latestMonth.split("-")[1]);
      return monthsRange(latestMonth, m); // Jan..latest of the latest year
    }
    const ys = new Set<string>();
    for (const p of Object.values(papers)) if (p.y) ys.add(p.y);
    return [...ys].sort();
  }, [frame, latestMonth, papers]);

  const gran: "month" | "year" = frame === "all" ? "year" : "month";
  const bucket = (d: string) => (gran === "year" ? d.slice(0, 4) : d.slice(0, 7));

  // rows: children of scope (each child is a "direction"); the children
  // partition the scope's papers, so the per-period scope total = sum of kids.
  const rows = useMemo(() => {
    const kids = scope.children && scope.children.length ? scope.children : [scope];
    const pset = new Set(periods);
    const n = periods.length;
    const recentN = gran === "month" ? 2 : 1;
    const earlyIdx = [...Array(n).keys()].slice(0, n - recentN);
    const lateIdx = [...Array(n).keys()].slice(n - recentN);
    const sumAt = (a: number[], idx: number[]) => idx.reduce((s, i) => s + a[i], 0);

    const base = kids.map((c) => {
      const counts: Record<string, number> = {};
      for (const doc of docsUnder(c.id, lens, tags)) {
        const d = papers[doc]?.d;
        if (!d) continue;
        const b = bucket(d);
        if (pset.has(b)) counts[b] = (counts[b] ?? 0) + 1;
      }
      const series = periods.map((p) => counts[p] ?? 0);
      return { node: c, series, total: series.reduce((a, b) => a + b, 0) };
    });
    const T = periods.map((_, i) => base.reduce((s, r) => s + r.series[i], 0)); // scope total / period
    const Tsum = T.reduce((a, b) => a + b, 0);

    const built = base.map((r) => {
      const shareSeries = periods.map((_, i) => (T[i] ? r.series[i] / T[i] : 0));
      const windowShare = Tsum ? r.total / Tsum : 0;
      const eT = sumAt(T, earlyIdx), lT = sumAt(T, lateIdx);
      const earlyShare = eT ? sumAt(r.series, earlyIdx) / eT : 0;
      const lateShare = lT ? sumAt(r.series, lateIdx) / lT : 0;
      const deltaShare = eT && lT ? lateShare - earlyShare : 0; // change in share (fraction)
      const latest = r.series[n - 1] ?? 0;
      const recent = sumAt(r.series, lateIdx);
      const countScore = r.total > 0 ? (recent / r.total) * Math.log2(r.total + 1) : 0;
      return { node: r.node, series: r.series, shareSeries, total: r.total,
               windowShare, deltaShare, latest, countScore };
    });

    if (metric === "share") {
      built.sort((a, b) => (sort === "top" ? b.windowShare - a.windowShare : b.deltaShare - a.deltaShare));
      return built.filter((r) => r.total >= 3);
    }
    built.sort((a, b) =>
      sort === "top" ? b.total - a.total : b.countScore - a.countScore || b.latest - a.latest,
    );
    return built.filter((r) => (sort === "top" ? r.total > 0 : r.total >= 3));
  }, [scope, periods, lens, tags, papers, sort, gran, metric]);

  const latestLabel = gran === "year" ? latestMonth.slice(0, 4) : monthLabel(latestMonth);

  // papers for the right panel: under picked node (or scope), within window, newest first
  const panelDocs = useMemo(() => {
    const id = picked ?? scope.id;
    const pset = new Set(periods);
    return docsUnder(id, lens, tags)
      .filter((d) => papers[d] && pset.has(bucket(papers[d].d)))
      .map((d) => ({ id: d, m: papers[d] }))
      .sort((a, b) => b.m.d.localeCompare(a.m.d));
  }, [picked, scope, periods, lens, tags, papers, gran]);

  const crumb = scope.id.split("/");

  return (
    <div className="trends">
      <div className="trends__controls">
        <div className="crumbs">
          {crumb.map((part, i) => {
            const id = crumb.slice(0, i + 1).join("/");
            const node = findNode(root, id);
            const last = i === crumb.length - 1;
            return (
              <span key={id}>
                {i > 0 && <span className="crumbs__sep">›</span>}
                <button
                  className={last ? "crumb crumb--on" : "crumb"}
                  onClick={() => { setScopeId(id); setPicked(null); }}
                >
                  {i === 0 ? "All" : node?.label ?? part}
                </button>
              </span>
            );
          })}
        </div>
        <div className="seg">
          {FRAMES.map((f) => (
            <button
              key={f.key}
              className={frame === f.key ? "seg__b seg__b--on" : "seg__b"}
              onClick={() => setFrame(f.key)}
            >
              {f.label}
            </button>
          ))}
          <span className="seg__div" />
          <button
            className={sort === "rising" ? "seg__b seg__b--on" : "seg__b"}
            onClick={() => setSort("rising")}
            title="Tags whose activity skews to the most recent period"
          >
            Emerging
          </button>
          <button
            className={sort === "top" ? "seg__b seg__b--on" : "seg__b"}
            onClick={() => setSort("top")}
          >
            Top
          </button>
          <span className="seg__div" />
          <button
            className={metric === "share" ? "seg__b seg__b--on" : "seg__b"}
            onClick={() => setMetric("share")}
            title="Each direction's % of the total, and how that share has shifted"
          >
            % Share
          </button>
          <button
            className={metric === "count" ? "seg__b seg__b--on" : "seg__b"}
            onClick={() => setMetric("count")}
          >
            Count
          </button>
        </div>
      </div>

      <div className="trends__body">
        <ol className="ranklist">
          {rows.map((r, i) => {
            const hasKids = (r.node.children?.length ?? 0) > 0;
            const isShare = metric === "share";
            const dpp = Math.round(r.deltaShare * 100);
            const hotCount = r.total ? Math.round((r.latest / r.total) * 100) >= 40 : false;
            return (
              <li
                key={r.node.id}
                className={`rank ${picked === r.node.id ? "rank--on" : ""}`}
                onClick={() => (hasKids ? (setScopeId(r.node.id), setPicked(null)) : setPicked(r.node.id))}
              >
                <span className="rank__n">{i + 1}</span>
                <span className="rank__label">
                  {r.node.label}
                  {hasKids && <span className="rank__drill">›</span>}
                </span>
                <Sparkline series={isShare ? r.shareSeries : r.series} color={accent} />
                <span className="rank__total">
                  {isShare ? `${Math.round(r.windowShare * 100)}%` : r.total}
                </span>
                {isShare ? (
                  <span
                    className={`rank__delta ${dpp > 0 ? "rank__delta--up" : dpp < 0 ? "rank__delta--down" : ""}`}
                    title="change in share of the total, earliest vs most recent in the window"
                  >
                    {dpp > 0 ? `▲ +${dpp}pp` : dpp < 0 ? `▼ ${dpp}pp` : "→ 0pp"}
                  </span>
                ) : (
                  <span className={`rank__delta ${hotCount ? "rank__delta--hot" : ""}`}>
                    {r.latest} in {latestLabel}
                  </span>
                )}
              </li>
            );
          })}
          {rows.length === 0 && <li className="rank rank--empty">No papers in this window.</li>}
        </ol>

        <aside className="panel">
          <div className="panel__head">
            <div className="panel__crumb">newest first · {frame === "all" ? "all years" : latestLabel + " window"}</div>
            <h2>{picked ? findNode(root, picked)?.label : scope.label}</h2>
            <div className="panel__count">{panelDocs.length.toLocaleString()} papers</div>
          </div>
          <ul className="papers">
            {panelDocs.slice(0, 200).map(({ id, m }) => (
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
        </aside>
      </div>
    </div>
  );
}

function monthLabel(ym: string): string {
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [y, m] = ym.split("-").map(Number);
  return `${names[m - 1]} ${y}`;
}

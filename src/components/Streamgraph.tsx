import { useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { useChart } from "../useChart";
import { PaperPanel } from "./PaperPanel";
import type { FacetKey, Papers, PaperTags, TaxNode } from "../types";

/** The slice of the ECharts instance the drill/hover hit-tests need. */
type ChartLike = {
  containPixel: (finder: object, value: number[]) => boolean;
  convertFromPixel: (finder: object, value: number[]) => number[];
};

const PALETTE = [
  "#3b82c4", "#d98b2b", "#5a9e6f", "#b5546b", "#7c6bd0", "#3aa6a6",
  "#c0903a", "#6b8fb5", "#9a6fb0", "#6fae8c", "#cf7a5b", "#8a8f98",
];
const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// How many trailing months of history to show. Enough to see the field ramp,
// short enough that the axis labels stay readable.
const WINDOW = 18;

function findNode(n: TaxNode, id: string): TaxNode | null {
  if (n.id === id) return n;
  for (const c of n.children ?? []) { const r = findNode(c, id); if (r) return r; }
  return null;
}
function docsUnder(id: string, lens: FacetKey, tags: PaperTags): string[] {
  const out: string[] = [];
  for (const [doc, t] of Object.entries(tags)) {
    const p = t[lens]; if (p && (p === id || p.startsWith(id + "/"))) out.push(doc);
  }
  return out;
}
function fmtMonth(ym: string, i: number): string {
  const [y, m] = ym.split("-");
  const mm = MONTH[Number(m) - 1];
  // Anchor the year on January and on the very first tick.
  return i === 0 || m === "01" ? `${mm} ’${y.slice(2)}` : mm;
}

type Band = {
  id: string; label: string; color: string;
  vals: number[]; rawVals: number[];
  subs: { label: string; vals: number[] }[];
};

/** Tooltip body for a hovered band: its subfields for month `mi`, biggest first. */
function tipHtml(b: Band, mi: number, months: string[]): string {
  const [y, m] = String(months[mi]).split("-");
  const when = `${MONTH[Number(m) - 1]} ’${y.slice(2)}`;
  const dot = `<span class="stip__dot" style="background:${b.color}"></span>`;
  const head = `<div class="stip__name">${dot}${b.label}</div>`
    + `<div class="stip__sub">${when} · ${b.rawVals[mi]} papers</div>`;
  const subs = b.subs
    .map((s) => ({ label: s.label, v: s.vals[mi] }))
    .filter((s) => s.v > 0)
    .sort((a, c) => c.v - a.v);
  if (!subs.length) return head + `<div class="stip__none">no subfields this month</div>`;
  const body = subs
    .map((s) => `<div class="stip__row"><span>${s.label}</span><b>${s.v}</b></div>`)
    .join("");
  return head + body;
}

export function Streamgraph({
  root, lens, tags, papers,
}: {
  root: TaxNode; lens: FacetKey; tags: PaperTags; papers: Papers;
}) {
  const [scopeId, setScopeId] = useState(root.id);
  const [mode, setMode] = useState<"volume" | "share">("volume");
  const scope = useMemo(() => findNode(root, scopeId) ?? root, [root, scopeId]);

  // The real time axis: every month that has papers, trimmed to the current
  // month (drop future-dated preprints) and to the last WINDOW months so the
  // ramp-up is visible without a long empty tail.
  const months = useMemo(() => {
    const now = new Date();
    const cap = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
    const s = new Set<string>();
    for (const p of Object.values(papers)) {
      const m = p.d.slice(0, 7);
      if (m && m <= cap) s.add(m);
    }
    const all = [...s].sort();
    return all.slice(-WINDOW);
  }, [papers]);

  const { option, bands } = useMemo(() => {
    const kids = scope.children?.length ? scope.children : [scope];
    const mset = new Set(months);
    const mIdx = Object.fromEntries(months.map((m, i) => [m, i]));
    // counts[childIdx][monthIdx]
    const counts = kids.map(() => months.map(() => 0));
    const monthTotal = months.map(() => 0);
    kids.forEach((c, ci) => {
      for (const doc of docsUnder(c.id, lens, tags)) {
        const d = papers[doc]?.d; if (!d) continue;
        const m = d.slice(0, 7);
        if (mset.has(m)) { counts[ci][mIdx[m]]++; monthTotal[mIdx[m]]++; }
      }
    });
    // Stack big, steady bands at the bottom so the river reads cleanly.
    const order = kids
      .map((_c, ci) => ({ ci, total: counts[ci].reduce((s, v) => s + v, 0) }))
      .filter((x) => x.total > 0)
      .sort((a, b) => b.total - a.total);

    // Per-month counts for each band's subfields (its direct children), so the
    // tooltip can break a band down into what's inside it. One pass over the
    // tagged docs, bucketed by the band-child id on each doc's path.
    const scopeLen = scope.id.split("/").length;
    const subCount: Record<string, number[]> = {};
    for (const c of kids) for (const sf of c.children ?? []) subCount[sf.id] = months.map(() => 0);
    for (const [doc, t] of Object.entries(tags)) {
      const p = t[lens];
      if (!p || !(p === scope.id || p.startsWith(scope.id + "/"))) continue;
      const parts = p.split("/");
      if (parts.length < scopeLen + 2) continue; // tagged at band level, no subfield
      const subId = parts.slice(0, scopeLen + 2).join("/");
      const arr = subCount[subId]; if (!arr) continue;
      const m = papers[doc]?.d.slice(0, 7);
      if (m && mset.has(m)) arr[mIdx[m]]++;
    }

    // Bands in stack order (bottom → top). `vals` drives the series; `rawVals`
    // and `subs` (always raw paper counts) feed the per-band tooltip.
    const bands = order.map(({ ci }, k) => {
      const c = kids[ci];
      const vals = months.map((_m, i) =>
        mode === "share"
          ? (monthTotal[i] ? Number(((counts[ci][i] / monthTotal[i]) * 100).toFixed(1)) : 0)
          : counts[ci][i],
      );
      const subs = (c.children ?? []).map((sf) => ({ label: sf.label, vals: subCount[sf.id] }));
      return { id: c.id, label: c.label, color: PALETTE[k % PALETTE.length], vals, rawVals: counts[ci], subs };
    });

    const series = bands.map((b) => ({
      name: b.label,
      type: "line" as const,
      stack: "total",
      smooth: 0.45,
      showSymbol: false,
      lineStyle: { width: 1, color: b.color },
      areaStyle: { color: b.color, opacity: 0.82 },
      emphasis: { focus: "series" as const },
      z: 2,
      data: b.vals,
    }));

    const opt: EChartsOption = {
      color: PALETTE,
      grid: { top: 64, bottom: 30, left: 46, right: 14 },
      legend: {
        type: "scroll",
        top: 6, left: 0, right: 0,
        itemWidth: 12, itemHeight: 12, itemGap: 14,
        textStyle: { color: "#566", fontSize: 12 },
      },
      tooltip: { show: false }, // replaced by a custom hover tooltip (see below)
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: months,
        axisLine: { lineStyle: { color: "#e6e9ee" } },
        axisTick: { show: false },
        axisLabel: {
          color: "#8a95a3", fontSize: 11, hideOverlap: true,
          formatter: (val: string, i: number) => fmtMonth(val, i),
        },
      },
      yAxis: {
        type: "value",
        max: mode === "share" ? 100 : undefined,
        splitLine: { lineStyle: { color: "#eef1f5" } },
        axisLabel: {
          color: "#8a95a3", fontSize: 11,
          formatter: (v: number) => (mode === "share" ? `${v}%` : `${v}`),
        },
      },
      series,
    };
    return { option: opt, bands };
  }, [scope, months, lens, tags, papers, mode]);

  // Filled areas don't emit their own pointer events, so we hit-test the raw
  // pixel: convert it to [monthIndex, value], then walk the stacked bands from
  // the bottom until the cumulative height passes the pointer — that's the band
  // under the cursor. Used for both drilling (click) and the hover tooltip.
  const hitBand = useMemo(
    () => (x: number, y: number, chart: ChartLike): { k: number; mi: number } | null => {
      if (!bands.length || !chart.containPixel({ gridIndex: 0 }, [x, y])) return null;
      const [xv, yv] = chart.convertFromPixel({ gridIndex: 0 }, [x, y]) as [number, number];
      const mi = Math.max(0, Math.min(months.length - 1, Math.round(xv)));
      let cum = 0;
      for (let k = 0; k < bands.length; k++) {
        cum += bands[k].vals[mi] ?? 0;
        if (yv <= cum) return { k, mi };
      }
      return null;
    },
    [bands, months],
  );

  const onPlotClick = useMemo(
    () => (x: number, y: number, chart: ChartLike) => {
      const hit = hitBand(x, y, chart);
      if (hit) setScopeId(bands[hit.k].id);
    },
    [hitBand, bands],
  );

  // Custom hover tooltip: positioned imperatively (no React re-render per move,
  // so the papers panel doesn't re-render while you sweep the chart).
  const tipRef = useRef<HTMLDivElement | null>(null);
  const onPlotMove = useMemo(
    () => (x: number, y: number, chart: ChartLike) => {
      const el = tipRef.current; if (!el) return;
      const hit = hitBand(x, y, chart);
      if (!hit) { el.style.display = "none"; return; }
      el.innerHTML = tipHtml(bands[hit.k], hit.mi, months);
      el.style.display = "block";
      const w = el.parentElement?.clientWidth ?? 0;
      // Flip to the left of the cursor when near the right edge so it stays in view.
      const flip = x > w * 0.62;
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      el.style.transform = flip ? "translate(-100%, -50%) translateX(-14px)" : "translate(0, -50%) translateX(14px)";
    },
    [hitBand, bands, months],
  );

  const onPlotOut = useMemo(
    () => () => { if (tipRef.current) tipRef.current.style.display = "none"; },
    [],
  );

  const ref = useChart(option, undefined, onPlotClick, onPlotMove, onPlotOut);

  const crumb = scope.id.split("/");
  return (
    <div className="stream">
      <div className="stream__controls">
        <div className="crumbs">
          {crumb.map((part, i) => {
            const id = crumb.slice(0, i + 1).join("/");
            const node = findNode(root, id);
            const last = i === crumb.length - 1;
            return (
              <span key={id}>
                {i > 0 && <span className="crumbs__sep">›</span>}
                <button className={last ? "crumb crumb--on" : "crumb"} onClick={() => setScopeId(id)}>
                  {i === 0 ? "All" : node?.label ?? part}
                </button>
              </span>
            );
          })}
        </div>
        <div className="seg">
          <button className={mode === "volume" ? "seg__b seg__b--on" : "seg__b"} onClick={() => setMode("volume")}>Volume</button>
          <button className={mode === "share" ? "seg__b seg__b--on" : "seg__b"} onClick={() => setMode("share")}>Share</button>
        </div>
      </div>
      <div className="stream__hint">
        Papers per month over the last {months.length} months · stacked by direction · a band that <b>swells</b> is emerging, one that <b>thins</b> is declining. Click a band to drill in and list its papers.
      </div>
      <div className="stream__body">
        <div className="stream__plot">
          <div className="streamchart" ref={ref} />
          <div className="stream__tip" ref={tipRef} />
        </div>
        <PaperPanel
          nodeId={scope.id === root.id ? null : scope.id}
          nodeLabel={scope.label}
          lens={lens}
          tags={tags}
          papers={papers}
          query=""
          emptyHint="Click a band to list its papers here, with links. Use the breadcrumb to step back out."
        />
      </div>
    </div>
  );
}

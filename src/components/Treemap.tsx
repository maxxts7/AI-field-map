import { useMemo } from "react";
import type { EChartsOption, ECElementEvent } from "echarts";
import { useChart } from "../useChart";
import type { TaxNode } from "../types";

// A pleasant, distinct hue per top-level category; descendants are shaded.
const PALETTE = [
  "#3b82c4", "#d98b2b", "#5a9e6f", "#b5546b",
  "#7c6bd0", "#3aa6a6", "#c0903a", "#8a8f98",
];

interface EcNode {
  name: string;
  value: number;
  id: string;
  children?: EcNode[];
}

function toEc(n: TaxNode): EcNode {
  const node: EcNode = { name: n.label, value: n.count, id: n.id };
  if (n.children && n.children.length) node.children = n.children.map(toEc);
  return node;
}

export function Treemap({
  root,
  onSelect,
}: {
  root: TaxNode;
  onSelect: (id: string, label: string) => void;
}) {
  const option = useMemo<EChartsOption>(() => {
    const data = (root.children ?? []).map(toEc);
    return {
      tooltip: {
        formatter: (info: unknown) => {
          const p = info as { name: string; value: number; treePathInfo?: { name: string }[] };
          const path = (p.treePathInfo ?? [])
            .slice(1)
            .map((x) => x.name)
            .join("  ›  ");
          return `<b>${p.name}</b><br/>${path || p.name}<br/><span style="color:#8a95a3">${p.value} papers</span>`;
        },
      },
      series: [
        {
          type: "treemap",
          id: "tax",
          name: root.label,
          roam: false,
          nodeClick: "zoomToNode",
          leafDepth: 2,
          drillDownIcon: "▸",
          width: "100%",
          height: "100%",
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          breadcrumb: {
            show: true,
            height: 26,
            bottom: 2,
            emptyItemWidth: 28,
            itemStyle: { color: "#eef1f5", borderColor: "#e6e9ee", textStyle: { color: "#56616f" } },
          },
          label: {
            show: true,
            formatter: "{b}",
            overflow: "truncate",
            fontSize: 12,
            color: "#fff",
            textShadowColor: "rgba(0,0,0,0.35)",
            textShadowBlur: 2,
          },
          upperLabel: {
            show: true,
            height: 22,
            fontSize: 11.5,
            color: "#fff",
            overflow: "truncate",
          },
          itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 },
          levels: [
            {
              color: PALETTE,
              colorMappingBy: "index",
              itemStyle: { borderWidth: 2, gapWidth: 2, borderColor: "#fff" },
              upperLabel: { show: false },
            },
            {
              colorSaturation: [0.32, 0.5],
              itemStyle: { borderWidth: 1, gapWidth: 1, borderColorSaturation: 0.6 },
            },
            {
              colorSaturation: [0.28, 0.45],
              itemStyle: { borderWidth: 1, gapWidth: 1, borderColorSaturation: 0.6 },
            },
            { colorSaturation: [0.25, 0.4] },
          ],
          data,
        },
      ],
    };
  }, [root]);

  const onClick = useMemo(
    () => (params: ECElementEvent) => {
      const d = params.data as { id?: string; name?: string } | undefined;
      if (d?.id) onSelect(d.id, d.name ?? "");
    },
    [onSelect],
  );

  const ref = useChart(option, onClick);
  return <div className="treemap" ref={ref} />;
}

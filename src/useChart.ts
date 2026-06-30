import { useEffect, useRef } from "react";
import type { EChartsOption, ECElementEvent } from "echarts";
import init from "./echarts";

type ChartInstance = ReturnType<typeof init.init>;
type ClickHandler = (params: ECElementEvent) => void;
type PlotPointerHandler = (x: number, y: number, chart: ChartInstance) => void;

/**
 * Minimal ECharts lifecycle hook: creates one instance per container, applies
 * `option` whenever it changes, wires an optional click handler, and keeps the
 * chart sized to its container. Uses the tree-shaken core build (./echarts).
 *
 * `onPlotClick` / `onPlotMove` receive raw canvas coordinates from zrender —
 * used for hit-testing filled areas (stacked line/area regions don't emit their
 * own series pointer events). `onPlotOut` fires when the pointer leaves.
 */
export function useChart(
  option: EChartsOption,
  onClick?: ClickHandler,
  onPlotClick?: PlotPointerHandler,
  onPlotMove?: PlotPointerHandler,
  onPlotOut?: (chart: ChartInstance) => void,
) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ChartInstance | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = init.init(ref.current);
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onClick) return;
    chart.on("click", onClick as (params: unknown) => void);
    return () => {
      chart.off("click", onClick as (params: unknown) => void);
    };
  }, [onClick]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onPlotClick) return;
    const zr = chart.getZr();
    const handler = (e: { offsetX: number; offsetY: number }) => onPlotClick(e.offsetX, e.offsetY, chart);
    zr.on("click", handler);
    return () => {
      zr.off("click", handler);
    };
  }, [onPlotClick]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || (!onPlotMove && !onPlotOut)) return;
    const zr = chart.getZr();
    const move = (e: { offsetX: number; offsetY: number }) => onPlotMove?.(e.offsetX, e.offsetY, chart);
    const out = () => onPlotOut?.(chart);
    if (onPlotMove) zr.on("mousemove", move);
    if (onPlotOut) zr.on("globalout", out);
    return () => {
      zr.off("mousemove", move);
      zr.off("globalout", out);
    };
  }, [onPlotMove, onPlotOut]);

  return ref;
}

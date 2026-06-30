// Tree-shaken ECharts. The explorer uses a TREEMAP (Explore mode) and a
// STACKED-AREA "river" (Evolution mode); register only what those need.
import * as echarts from "echarts/core";
import { TreemapChart, LineChart } from "echarts/charts";
import {
  TooltipComponent,
  GridComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  TreemapChart,
  LineChart,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  CanvasRenderer,
]);

export default echarts;

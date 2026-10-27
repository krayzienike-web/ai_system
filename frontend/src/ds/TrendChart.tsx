import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { Table2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { num } from "../lib/format";
import type { FindingView } from "../api/types";

type ChartSpec = NonNullable<FindingView["chart"]>;
import { Button } from "./primitives";

echarts.use([LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, SVGRenderer]);

// Categorical slots 1–2 of the validated reference palette; text stays in ink colors.
const SERIES_RESTAURANT = "#0a8f84";
const SERIES_NETWORK = "#eb6834";
const INK_SECONDARY = "#3d4a57";
const GRID = "#dfe6e3";

const fmt = (value: number, unit: string) => (unit === "%" ? `${value.toLocaleString("ru-RU")}%` : `${num(value)} ${unit}`);

export function TrendChart({ spec, restaurantLabel = "Ресторан" }: { spec: ChartSpec; restaurantLabel?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [asTable, setAsTable] = useState(false);

  useEffect(() => {
    if (asTable || !ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    const series = [
      {
        name: restaurantLabel,
        data: spec.restaurant,
        color: SERIES_RESTAURANT,
        endLabel: { show: true, formatter: restaurantLabel, color: INK_SECONDARY },
        markLine:
          spec.norm !== undefined && spec.norm !== null
            ? {
                silent: true,
                symbol: "none",
                lineStyle: { color: "#14202b", type: "dashed", width: 1.5 },
                label: { formatter: spec.norm_label ?? "Норма", color: INK_SECONDARY, position: "insideEndBottom" },
                data: [{ yAxis: spec.norm }],
              }
            : undefined,
      },
      ...(spec.network_avg
        ? [
            {
              name: "Среднее по сети",
              data: spec.network_avg,
              color: SERIES_NETWORK,
              endLabel: { show: true, formatter: "Среднее по сети", color: INK_SECONDARY },
            },
          ]
        : []),
    ].map((s) => ({
      ...s,
      type: "line" as const,
      lineStyle: { width: 2.5 },
      symbol: "circle",
      symbolSize: 8,
      itemStyle: { borderColor: "#fff", borderWidth: 2 },
      emphasis: { focus: "series" as const },
    }));

    chart.setOption({
      animationDuration: 700,
      textStyle: { fontFamily: "Onest, sans-serif" },
      grid: { left: 8, right: 120, top: 36, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 4, textStyle: { color: INK_SECONDARY } },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", lineStyle: { color: "#a8a29e" } },
        valueFormatter: (v: unknown) => fmt(Number(v), spec.unit),
      },
      xAxis: {
        type: "category",
        data: spec.labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: GRID } },
        axisTick: { show: false },
        axisLabel: { color: INK_SECONDARY },
      },
      yAxis: {
        type: "value",
        scale: spec.unit !== "%",
        splitLine: { lineStyle: { color: GRID } },
        axisLabel: { color: INK_SECONDARY, formatter: (v: number) => fmt(v, spec.unit) },
      },
      series,
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [spec, restaurantLabel, asTable]);

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm text-ink-3">{spec.title}</div>
        <Button variant="ghost" size="sm" onClick={() => setAsTable((v) => !v)} aria-pressed={asTable}>
          <Table2 size={14} /> {asTable ? "График" : "Таблица"}
        </Button>
      </div>
      {asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-ink-3">
              <tr>
                <th className="py-1 pr-4 font-normal">Период</th>
                <th className="py-1 pr-4 text-right font-normal">{restaurantLabel}</th>
                {spec.network_avg && <th className="py-1 text-right font-normal">Среднее по сети</th>}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {spec.labels.map((label, i) => (
                <tr key={label} className="border-t border-line">
                  <td className="py-1 pr-4">{label}</td>
                  <td className="py-1 pr-4 text-right">{fmt(spec.restaurant[i] ?? 0, spec.unit)}</td>
                  {spec.network_avg && <td className="py-1 text-right">{fmt(spec.network_avg[i] ?? 0, spec.unit)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={ref} className="h-64 w-full" role="img" aria-label={spec.title} />
      )}
    </div>
  );
}

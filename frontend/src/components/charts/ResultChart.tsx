import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatMoney, formatMoneyCompact, humanize } from "@/lib/format";

import { BarList } from "./BarList";
import { chartSpec } from "./chartSpec";
import type { TooltipProps } from "./types";
import { useChartColors } from "./useChartColors";

function format(value: number, money: boolean) {
  return money ? formatMoney(value, { whole: true }) : value.toLocaleString("en-IN");
}

export function ResultChart({
  columns,
  rows,
  kind,
}: {
  columns: string[];
  rows: unknown[][];
  kind: "bar" | "line" | "table";
}) {
  const colors = useChartColors();
  const spec = chartSpec(columns, rows);
  if (!spec || kind === "table") return null;
  const metric = humanize(columns[spec.valueIndex] ?? "value");

  if (kind === "line") {
    const data = rows.map((row) => ({ label: String(row[spec.labelIndex]), value: Number(row[spec.valueIndex] ?? 0) }));
    const LineTip = ({ active, payload }: TooltipProps) => {
      const point = payload?.[0]?.payload as { label: string; value: number } | undefined;
      if (!active || !point) return null;
      return (
        <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] shadow-pop">
          <div className="text-[13px] font-semibold text-ink tabular">{format(point.value, spec.money)}</div>
          <div className="mt-0.5 text-ink-2">{point.label}</div>
        </div>
      );
    };
    return (
      <figure className="m-0">
        <figcaption className="mb-2 text-[12px] text-ink-3">{metric}</figcaption>
        <div className="h-56">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={colors.grid} />
              <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: colors.axis }} tick={{ fill: colors.label, fontSize: 12 }} />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={64}
                tick={{ fill: colors.label, fontSize: 12 }}
                tickFormatter={(v: number) => (spec.money ? formatMoneyCompact(v) : v.toLocaleString("en-IN"))}
              />
              <Tooltip content={LineTip} cursor={{ stroke: colors.axis, strokeWidth: 1 }} isAnimationActive={false} />
              <Line
                type="monotone"
                dataKey="value"
                stroke={colors.series}
                strokeWidth={2}
                dot={{ r: 4, fill: colors.series, stroke: colors.surface, strokeWidth: 2 }}
                activeDot={{ r: 5, fill: colors.series, stroke: colors.surface, strokeWidth: 2 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </figure>
    );
  }

  const items = rows.slice(0, 15).map((row, index) => {
    const value = Number(row[spec.valueIndex] ?? 0);
    return {
      key: `${index}`,
      label: String(row[spec.labelIndex] ?? "—"),
      value,
      display: spec.money ? formatMoneyCompact(value) : value.toLocaleString("en-IN"),
    };
  });
  return (
    <figure className="m-0">
      <figcaption className="mb-3 text-[12px] text-ink-3">{metric}</figcaption>
      <BarList items={items} ariaLabel={metric} />
    </figure>
  );
}

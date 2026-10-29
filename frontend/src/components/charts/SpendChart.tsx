import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatMoney, formatMoneyCompact, formatMonth } from "@/lib/format";

import type { TooltipProps } from "./types";
import { useChartColors } from "./useChartColors";

interface Point {
  period: string;
  spend: number;
  invoices: number;
}

function SpendTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload as Point | undefined;
  if (!active || !point) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[12px] shadow-pop">
      <div className="text-[13px] font-semibold text-ink tabular">{formatMoney(point.spend, { whole: true })}</div>
      <div className="mt-0.5 text-ink-2">
        {formatMonth(point.period)} · {point.invoices} invoice{point.invoices === 1 ? "" : "s"}
      </div>
    </div>
  );
}

/** Single series, so no legend: the card title names it. A screen-reader table carries every value. */
export function SpendChart({ data, className = "h-64" }: { data: Point[]; className?: string }) {
  const colors = useChartColors();
  return (
    <figure className="m-0 flex h-full flex-col">
      <div className={`w-full ${className}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap="30%">
            <CartesianGrid vertical={false} stroke={colors.grid} strokeWidth={1} />
            <XAxis
              dataKey="period"
              tickFormatter={formatMonth}
              tickLine={false}
              axisLine={{ stroke: colors.axis }}
              tick={{ fill: colors.label, fontSize: 12 }}
              interval="preserveStartEnd"
              minTickGap={8}
            />
            <YAxis
              tickFormatter={(v: number) => (v === 0 ? "0" : formatMoneyCompact(v))}
              tickLine={false}
              axisLine={false}
              tick={{ fill: colors.label, fontSize: 12 }}
              width={64}
            />
            <Tooltip content={SpendTooltip} cursor={{ fill: colors.hover }} isAnimationActive={false} />
            <Bar
              dataKey="spend"
              fill={colors.series}
              radius={[4, 4, 0, 0]}
              maxBarSize={24}
              isAnimationActive={false}
              activeBar={{ fill: colors.series, fillOpacity: 0.8 }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="sr-only">
        <caption>Approved spend by month</caption>
        <thead>
          <tr>
            <th>Month</th>
            <th>Spend</th>
            <th>Invoices</th>
          </tr>
        </thead>
        <tbody>
          {data.map((p) => (
            <tr key={p.period}>
              <td>{formatMonth(p.period)}</td>
              <td>{formatMoney(p.spend)}</td>
              <td>{p.invoices}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

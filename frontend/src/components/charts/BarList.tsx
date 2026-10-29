import type { ReactNode } from "react";

export interface BarListItem {
  key: string;
  label: ReactNode;
  value: number;
  display: ReactNode;
  hint?: ReactNode;
  href?: string;
}

/**
 * Horizontal bars for ranked categories: one series colour, thin rounded-end bars from a shared
 * baseline, value at the tip in text ink. The row itself is the hover target.
 */
export function BarList({ items, ariaLabel }: { items: BarListItem[]; ariaLabel: string }) {
  const max = Math.max(...items.map((i) => i.value), 0);
  return (
    <ul className="space-y-3" aria-label={ariaLabel}>
      {items.map((item) => {
        const width = max > 0 ? Math.max(2, (item.value / max) * 100) : 0;
        return (
          <li key={item.key} className="group" title={typeof item.hint === "string" ? item.hint : undefined}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-ink-2 group-hover:text-ink">{item.label}</span>
              <span className="tabular shrink-0 font-medium text-ink">{item.display}</span>
            </div>
            <div className="h-2 w-full">
              <div
                className="h-2 rounded-r-[4px] bg-[var(--chart-series)] transition-opacity group-hover:opacity-80"
                style={{ width: `${width}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

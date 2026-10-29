const MONEY = /spend|amount|total|value|price/i;
const PREFERRED = /spend|total_amount|amount|occurrences|avg_hours|stp_rate|invoices|count|^n$/i;

export interface ChartSpec {
  labelIndex: number;
  valueIndex: number;
  money: boolean;
}

/** Pick a category column and the most meaningful numeric column, or null when the result isn't chartable. */
export function chartSpec(columns: string[], rows: unknown[][]): ChartSpec | null {
  if (rows.length < 2 || columns.length < 2) return null;
  const numeric = columns
    .map((_, i) => i)
    .filter((i) => rows.every((row) => typeof row[i] === "number" || row[i] === null));
  const labelIndex = columns.findIndex((_, i) => !numeric.includes(i));
  if (labelIndex === -1 || numeric.length === 0) return null;
  const valueIndex =
    numeric.find((i) => MONEY.test(columns[i] ?? "")) ??
    numeric.find((i) => PREFERRED.test(columns[i] ?? "")) ??
    numeric[numeric.length - 1]!;
  return { labelIndex, valueIndex, money: MONEY.test(columns[valueIndex] ?? "") };
}

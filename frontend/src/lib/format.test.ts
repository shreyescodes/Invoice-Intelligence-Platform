import { describe, expect, it } from "vitest";

import { formatHours, formatMoney, formatMoneyCompact, formatPercent, formatRelative, humanize, initials } from "./format";

describe("money", () => {
  it("formats API fixed-point strings with Indian grouping", () => {
    expect(formatMoney("1234567.50")).toBe("₹12,34,567.50");
    expect(formatMoney(96170, { whole: true })).toBe("₹96,170");
    expect(formatMoney(null)).toBe("—");
  });

  it("uses lakh and crore for compact values", () => {
    expect(formatMoneyCompact(485000)).toBe("₹4.85 L");
    expect(formatMoneyCompact("12400000")).toBe("₹1.24 Cr");
    expect(formatMoneyCompact(96170)).toBe("₹96.2K");
    expect(formatMoneyCompact(950)).toBe("₹950");
  });
});

describe("other formatters", () => {
  it("formats percentages and durations", () => {
    expect(formatPercent(0.873)).toBe("87.3%");
    expect(formatPercent(1)).toBe("100%");
    expect(formatHours(0.25)).toBe("15 min");
    expect(formatHours(5.04)).toBe("5 h");
    expect(formatHours(72)).toBe("3 d");
  });

  it("describes relative time", () => {
    const now = new Date("2026-10-29T12:00:00Z");
    expect(formatRelative("2026-10-29T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-10-29T10:00:00Z", now)).toBe("2 hours ago");
    expect(formatRelative("2026-10-27T12:00:00Z", now)).toBe("2 days ago");
  });

  it("humanizes codes and builds initials", () => {
    expect(humanize("GOODS_RECEIPT")).toBe("Goods receipt");
    expect(initials("Arjun Mehta")).toBe("AM");
  });
});

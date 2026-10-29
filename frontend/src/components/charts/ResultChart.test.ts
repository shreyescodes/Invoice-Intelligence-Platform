import { describe, expect, it } from "vitest";

import { chartSpec } from "./chartSpec";

describe("chartSpec", () => {
  it("picks the category column and the money column", () => {
    const spec = chartSpec(["vendor_name", "invoices", "total_spend"], [
      ["Kaveri", 4, 120000],
      ["Bluepeak", 2, 90000],
    ]);
    expect(spec).toEqual({ labelIndex: 0, valueIndex: 2, money: true });
  });

  it("returns null for results that are not chartable", () => {
    expect(chartSpec(["invoice_number"], [["A"], ["B"]])).toBeNull();
    expect(chartSpec(["vendor_name", "n"], [["only one row", 1]])).toBeNull();
    expect(chartSpec(["a", "b"], [["x", "y"], ["z", "w"]])).toBeNull();
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskMeter } from "@/components/RiskMeter";

import { StatusBadge } from "./Badge";

describe("StatusBadge", () => {
  it("always renders a text label next to the colour", () => {
    render(<StatusBadge status="needs_review" />);
    expect(screen.getByText("Needs review")).toBeInTheDocument();
  });
});

describe("RiskMeter", () => {
  it("exposes the score and risk level to assistive technology", () => {
    render(<RiskMeter score={0.82} threshold={0.5} />);
    expect(screen.getByRole("meter")).toHaveAccessibleName("Anomaly score 0.82, High risk");
  });

  it("renders a dash when the invoice has not been scored", () => {
    render(<RiskMeter score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

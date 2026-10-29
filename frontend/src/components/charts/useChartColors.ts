import { useMemo } from "react";

import { useTheme } from "@/lib/theme";

export interface ChartColors {
  series: string;
  seriesSoft: string;
  grid: string;
  axis: string;
  label: string;
  surface: string;
  ink: string;
  hover: string;
}

/** SVG attributes cannot read CSS variables reliably, so resolve the tokens for the active theme. */
export function useChartColors(): ChartColors {
  const [theme] = useTheme();
  return useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    return {
      series: read("--chart-series", "#2a78d6"),
      seriesSoft: read("--chart-series-soft", "#b7d3f6"),
      grid: read("--chart-grid", "#e1e0d9"),
      axis: read("--chart-axis", "#c3c2b7"),
      label: read("--chart-label", "#898781"),
      surface: read("--surface", "#ffffff"),
      ink: read("--ink", "#111110"),
      hover: read("--surface-hover", "#f3f3f0"),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recompute when the theme flips
  }, [theme]);
}

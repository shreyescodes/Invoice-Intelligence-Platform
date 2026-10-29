import { clsx } from "clsx";

import { riskLevel, TONE_CLASSES } from "@/lib/status";

/** Meter: the fill carries severity, the track is a light step of the same scale. */
export function RiskMeter({
  score,
  threshold = 0.5,
  size = "sm",
}: {
  score: number | null | undefined;
  threshold?: number;
  size?: "sm" | "lg";
}) {
  const level = riskLevel(score, threshold);
  if (score === null || score === undefined) return <span className="text-[13px] text-ink-3">—</span>;
  const pct = Math.max(4, Math.round(score * 100));
  return (
    // A native <meter> cannot draw the review-threshold tick, so the ARIA meter role is used instead.
    <div
      className={clsx("flex items-center gap-2", size === "lg" ? "w-full" : "w-28")}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={1}
      aria-valuenow={score}
      aria-label={`Anomaly score ${score.toFixed(2)}, ${level.label} risk`}
    >
      <div className={clsx("relative flex-1 rounded-full bg-surface-hover", size === "lg" ? "h-2" : "h-1.5")}>
        <div
          className={clsx("absolute inset-y-0 left-0 rounded-full", TONE_CLASSES[level.tone].dot)}
          style={{ width: `${pct}%` }}
        />
        <div
          className="absolute inset-y-[-3px] w-px bg-ink-3"
          style={{ left: `${threshold * 100}%` }}
          title={`Review threshold ${threshold.toFixed(2)}`}
        />
      </div>
      <span className={clsx("tabular w-8 text-right text-[12px] font-medium", TONE_CLASSES[level.tone].ink)}>
        {score.toFixed(2)}
      </span>
    </div>
  );
}

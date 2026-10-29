/** The subset of Recharts' tooltip props our custom tooltips read. */
export interface TooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
}

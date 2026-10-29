import { clsx } from "clsx";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { InvoiceStatus } from "@/lib/api";
import { STATUS, TONE_CLASSES, type Tone } from "@/lib/status";

export function ToneBadge({
  tone,
  icon: Icon,
  children,
  className,
}: {
  tone: Tone;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
}) {
  const classes = TONE_CLASSES[tone];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] leading-4 font-medium whitespace-nowrap",
        classes.soft,
        classes.ink,
        className,
      )}
    >
      {Icon && <Icon className={clsx("size-3.5", classes.icon)} aria-hidden strokeWidth={2.25} />}
      {children}
    </span>
  );
}

/** Status is always icon + label, never colour alone. */
export function StatusBadge({ status }: { status: InvoiceStatus }) {
  const meta = STATUS[status];
  return (
    <ToneBadge tone={meta.tone} icon={meta.icon}>
      <span title={meta.description}>{meta.label}</span>
    </ToneBadge>
  );
}

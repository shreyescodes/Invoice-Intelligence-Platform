import { clsx } from "clsx";
import { CircleAlert, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { TONE_CLASSES, type Tone } from "@/lib/status";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <output className={clsx("inline-flex items-center gap-2 text-ink-3", className)}>
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span className="text-[13px]">{label}…</span>
    </output>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon: LucideIcon;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex flex-col items-center px-6 py-12 text-center", className)}>
      <div className="mb-3 grid size-10 place-items-center rounded-full bg-surface-2 ring-1 ring-line">
        <Icon className="size-5 text-ink-3" aria-hidden />
      </div>
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-[13px] text-ink-2">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Callout({
  tone,
  icon: Icon = CircleAlert,
  title,
  children,
  className,
}: {
  tone: Tone;
  icon?: LucideIcon;
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const classes = TONE_CLASSES[tone];
  return (
    <div className={clsx("flex gap-3 rounded-xl border border-line px-4 py-3", classes.soft, className)}>
      <Icon className={clsx("mt-0.5 size-4 shrink-0", classes.icon)} aria-hidden strokeWidth={2.25} />
      <div className="min-w-0 text-[13px]">
        <div className="font-semibold text-ink">{title}</div>
        {children && <div className="mt-1 text-ink-2">{children}</div>}
      </div>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <Callout tone="critical" title="Something went wrong">
      {error.message}
      {onRetry && (
        <button type="button" onClick={onRetry} className="ml-2 font-medium text-accent-ink underline">
          Try again
        </button>
      )}
    </Callout>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-surface-hover", className)} />;
}

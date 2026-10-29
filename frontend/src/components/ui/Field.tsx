import { clsx } from "clsx";
import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

const control =
  "w-full rounded-lg border border-line-strong bg-surface px-3 text-sm text-ink placeholder:text-ink-3 " +
  "shadow-card transition-colors focus:border-accent focus:outline-none focus:ring-3 focus:ring-accent/20 " +
  "disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { icon?: ReactNode }>(
  function Input({ className, icon, ...props }, ref) {
    if (!icon) return <input ref={ref} className={clsx(control, "h-9", className)} {...props} />;
    return (
      <div className={clsx("relative", className)}>
        <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-ink-3">{icon}</span>
        <input ref={ref} className={clsx(control, "h-9 pl-9")} {...props} />
      </div>
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return <textarea ref={ref} className={clsx(control, "min-h-24 py-2", className)} {...props} />;
  },
);

export function Label({ htmlFor, children, hint }: { htmlFor: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 flex items-baseline justify-between text-[13px] font-medium text-ink">
      {children}
      {hint && <span className="font-normal text-ink-3">{hint}</span>}
    </label>
  );
}

export function Select({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx(control, "h-9 appearance-auto pr-8", className)} {...props}>
      {children}
    </select>
  );
}

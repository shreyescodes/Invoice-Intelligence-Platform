import {
  Ban,
  CircleCheck,
  CircleX,
  Clock,
  Loader,
  OctagonAlert,
  SendHorizontal,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import type { InvoiceStatus } from "./api";

export type Tone = "neutral" | "info" | "good" | "warning" | "serious" | "critical";

export const STATUS: Record<InvoiceStatus, { label: string; tone: Tone; icon: LucideIcon; description: string }> = {
  received: { label: "Received", tone: "neutral", icon: Clock, description: "Queued for processing" },
  processing: { label: "Processing", tone: "info", icon: Loader, description: "Extracting and validating" },
  needs_review: { label: "Needs review", tone: "warning", icon: TriangleAlert, description: "Waiting for an approver" },
  approved: { label: "Approved", tone: "info", icon: SendHorizontal, description: "Posting to the ERP" },
  posted: { label: "Posted", tone: "good", icon: CircleCheck, description: "Booked in the ERP" },
  rejected: { label: "Rejected", tone: "neutral", icon: Ban, description: "Rejected by an approver" },
  failed: { label: "Failed", tone: "critical", icon: OctagonAlert, description: "Needs operator attention" },
};

export const TONE_CLASSES: Record<Tone, { soft: string; ink: string; icon: string; dot: string }> = {
  neutral: { soft: "bg-neutral-soft", ink: "text-ink-2", icon: "text-ink-3", dot: "bg-ink-3" },
  info: { soft: "bg-accent-soft", ink: "text-accent-ink", icon: "text-accent", dot: "bg-accent" },
  good: { soft: "bg-good-soft", ink: "text-good-ink", icon: "text-good", dot: "bg-good" },
  warning: { soft: "bg-warning-soft", ink: "text-warning-ink", icon: "text-warning", dot: "bg-warning" },
  serious: { soft: "bg-serious-soft", ink: "text-serious-ink", icon: "text-serious", dot: "bg-serious" },
  critical: { soft: "bg-critical-soft", ink: "text-critical-ink", icon: "text-critical", dot: "bg-critical" },
};

export const CHECK_STATUS = {
  pass: { label: "Passed", tone: "good" as Tone, icon: CircleCheck },
  warn: { label: "Warning", tone: "warning" as Tone, icon: TriangleAlert },
  fail: { label: "Failed", tone: "critical" as Tone, icon: CircleX },
};

export const PENDING_STATUSES: InvoiceStatus[] = ["received", "processing", "approved"];

export const CHECK_LABELS: Record<string, string> = {
  REQUIRED_FIELDS: "Required fields",
  VENDOR_MATCH: "Vendor master",
  DUPLICATE: "Duplicate check",
  LINE_TOTALS: "Line totals",
  INVOICE_TOTAL: "Invoice total",
  TAX_RATE: "Tax rate",
  DATES: "Dates",
  PO_MATCH: "Purchase order",
  PRICE_MATCH: "Price match (2-way)",
  GOODS_RECEIPT: "Goods receipt (3-way)",
};

export function riskLevel(score: number | null | undefined, threshold = 0.5): {
  label: string;
  tone: Tone;
} {
  if (score === null || score === undefined) return { label: "Not scored", tone: "neutral" };
  if (score >= threshold) return { label: "High", tone: "critical" };
  if (score >= threshold * 0.6) return { label: "Elevated", tone: "warning" };
  return { label: "Low", tone: "info" };
}

import { clsx } from "clsx";
import { ArrowLeft, Check, CircleAlert, FileSearch, Loader2, OctagonAlert, RotateCcw, TriangleAlert, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";

import { DocumentPreview } from "@/components/DocumentPreview";
import { RiskMeter } from "@/components/RiskMeter";
import { StatusBadge, ToneBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader } from "@/components/ui/Card";
import { Dialog } from "@/components/ui/Dialog";
import { Callout, EmptyState, ErrorState, Skeleton, Spinner } from "@/components/ui/Feedback";
import { Label, Textarea } from "@/components/ui/Field";
import { ApiError, type InvoiceDetail } from "@/lib/api";
import { formatDate, formatDateTime, formatMoney, formatPercent, formatRelative, humanize } from "@/lib/format";
import { useDecision, useInvoice, useMeta } from "@/lib/queries";
import { CHECK_LABELS, CHECK_STATUS, riskLevel, STATUS, TONE_CLASSES } from "@/lib/status";

const EXTRACTION_METHOD: Record<string, string> = {
  pdf_text: "PDF text layer",
  "pdf_text+llm": "PDF text layer, refined by LLM",
  embedded_cii: "Embedded e-invoice (ZUGFeRD / Factur-X)",
  azure_document_intelligence: "Azure Document Intelligence",
  "azure_document_intelligence+llm": "Azure Document Intelligence, refined by LLM",
};

const EVENT_LABEL: Record<string, string> = {
  uploaded: "Uploaded",
  processing_started: "Processing started",
  auto_approved: "Auto-approved by policy",
  routed_to_review: "Routed to review",
  approved: "Approved",
  rejected: "Rejected",
  posted_to_erp: "Posted to ERP",
  retry_scheduled: "Retry scheduled",
  retried: "Retried by operator",
  failed: "Failed",
};

function Field({ label, children, confidence }: { label: string; children: ReactNode; confidence?: number }) {
  const low = confidence !== undefined && confidence < 0.8;
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-[12px] text-ink-3">
        {label}
        {low && (
          <span title={`Extraction confidence ${formatPercent(confidence, 0)}`} className="inline-flex">
            <CircleAlert className="size-3.5 text-warning" aria-label={`Low confidence ${formatPercent(confidence, 0)}`} />
          </span>
        )}
      </dt>
      <dd className="mt-0.5 truncate text-[13px] text-ink">{children}</dd>
    </div>
  );
}

function DecisionDialog({
  invoice,
  mode,
  onClose,
}: {
  invoice: InvoiceDetail;
  mode: "approve" | "reject" | null;
  onClose: () => void;
}) {
  const [comment, setComment] = useState("");
  const { approve, reject } = useDecision(invoice.id);
  const mutation = mode === "reject" ? reject : approve;

  const submit = async () => {
    try {
      if (mode === "reject") await reject.mutateAsync(comment.trim());
      else await approve.mutateAsync(comment.trim() || null);
      toast.success(mode === "reject" ? "Invoice rejected" : "Invoice approved and queued for ERP posting");
      setComment("");
      onClose();
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : "The decision could not be saved");
    }
  };

  return (
    <Dialog
      open={mode !== null}
      onClose={onClose}
      title={mode === "reject" ? "Reject invoice" : "Approve invoice"}
      description={`${invoice.vendor?.name ?? invoice.vendor_name ?? "Unknown vendor"} · ${invoice.invoice_number ?? ""} · ${formatMoney(invoice.total_amount)}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant={mode === "reject" ? "danger" : "primary"}
            loading={mutation.isPending}
            disabled={mode === "reject" && comment.trim().length < 3}
            onClick={() => void submit()}
          >
            {mode === "reject" ? "Reject invoice" : "Approve and post"}
          </Button>
        </>
      }
    >
      {mode === "approve" && (invoice.review_reasons?.length ?? 0) > 0 && (
        <Callout tone="warning" icon={TriangleAlert} title="You are overriding these exceptions" className="mb-4">
          <ul className="list-disc pl-4">
            {invoice.review_reasons?.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Callout>
      )}
      <Label htmlFor="decision-comment" hint={mode === "reject" ? "Required" : "Optional"}>
        {mode === "reject" ? "Reason for rejection" : "Comment"}
      </Label>
      <Textarea
        id="decision-comment"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder={mode === "reject" ? "Shared with the AP team and kept in the audit trail" : "Recorded in the audit trail"}
        maxLength={2000}
      />
    </Dialog>
  );
}

function ChecksCard({ invoice }: { invoice: InvoiceDetail }) {
  const order = { fail: 0, warn: 1, pass: 2 } as const;
  const checks = [...invoice.checks].sort((a, b) => order[a.status] - order[b.status]);
  const failed = checks.filter((c) => c.status !== "pass").length;
  return (
    <Card>
      <CardHeader
        title="Validation"
        description={checks.length ? `${checks.length - failed} of ${checks.length} checks passed` : "Not run yet"}
      />
      <ul className="divide-y divide-line border-t border-line">
        {checks.map((check) => {
          const meta = CHECK_STATUS[check.status];
          const Icon = meta.icon;
          return (
            <li key={check.code} className="flex gap-3 px-5 py-2.5">
              <Icon className={clsx("mt-0.5 size-4 shrink-0", TONE_CLASSES[meta.tone].icon)} aria-label={meta.label} />
              <div className="min-w-0">
                <div className="text-[13px] font-medium text-ink">{CHECK_LABELS[check.code] ?? humanize(check.code)}</div>
                <div className="text-[13px] text-ink-2">{check.message}</div>
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function RiskCard({ invoice, threshold }: { invoice: InvoiceDetail; threshold: number }) {
  const level = riskLevel(invoice.anomaly_score, threshold);
  return (
    <Card>
      <CardHeader
        title="Anomaly score"
        description={invoice.model_version ? `Isolation forest · ${invoice.model_version}` : "Not scored"}
        action={<ToneBadge tone={level.tone}>{level.label} risk</ToneBadge>}
      />
      <div className="px-5 pb-4">
        <RiskMeter score={invoice.anomaly_score} threshold={threshold} size="lg" />
        <p className="mt-1.5 text-[12px] text-ink-3">Review threshold {threshold.toFixed(2)}, compared with this vendor's history.</p>
        {(invoice.anomaly_reasons?.length ?? 0) > 0 && (
          <ul className="mt-3 space-y-1.5">
            {invoice.anomaly_reasons?.map((reason) => (
              <li key={reason} className="flex gap-2 text-[13px] text-ink-2">
                <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-ink-3" aria-hidden />
                {reason}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

function Timeline({ invoice }: { invoice: InvoiceDetail }) {
  return (
    <Card>
      <CardHeader title="Activity" description="Audit trail" />
      <ol className="px-5 pb-5">
        {invoice.events.map((event, index) => {
          const last = index === invoice.events.length - 1;
          const tone =
            event.action === "failed"
              ? "critical"
              : event.action === "rejected"
                ? "neutral"
                : event.action === "routed_to_review" || event.action === "retry_scheduled"
                  ? "warning"
                  : event.action === "posted_to_erp" || event.action.includes("approved")
                    ? "good"
                    : "info";
          return (
            <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
              {!last && <span className="absolute top-4 bottom-0 left-[5px] w-px bg-line" aria-hidden />}
              <span className={clsx("relative mt-1.5 size-[11px] shrink-0 rounded-full ring-2 ring-surface", TONE_CLASSES[tone].dot)} />
              <div className="min-w-0 text-[13px]">
                <div className="text-ink">
                  <span className="font-medium">{EVENT_LABEL[event.action] ?? humanize(event.action)}</span>
                  {event.actor && <span className="text-ink-2"> by {event.actor.full_name}</span>}
                </div>
                <div className="text-[12px] text-ink-3" title={formatDateTime(event.created_at)}>
                  {formatDateTime(event.created_at)}
                </div>
                {event.comment && <div className="mt-1 rounded-md bg-surface-2 px-2 py-1 text-ink-2">{event.comment}</div>}
                {event.action === "posted_to_erp" && typeof event.details?.document_number === "string" && (
                  <div className="mt-0.5 text-[12px] text-ink-2">Document {event.details.document_number}</div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

interface LineIssues {
  price: Map<number, { poPrice: string; variance: string }>;
  receipt: Map<string, string>;
}

/** Pull per-line findings out of the PRICE_MATCH and GOODS_RECEIPT check details. */
function lineIssues(invoice: InvoiceDetail): LineIssues {
  const price = new Map<number, { poPrice: string; variance: string }>();
  const receipt = new Map<string, string>();
  for (const check of invoice.checks) {
    if (check.status !== "fail" || !check.details) continue;
    if (check.code === "PRICE_MATCH" && Array.isArray(check.details.lines)) {
      for (const line of check.details.lines as { line: string; po_price: string; variance_pct: string }[]) {
        price.set(Number(line.line), { poPrice: line.po_price, variance: line.variance_pct });
      }
    }
    if (check.code === "GOODS_RECEIPT" && Array.isArray(check.details.items)) {
      for (const item of check.details.items as { po_item: string; open: string }[]) {
        receipt.set(item.po_item, item.open);
      }
    }
  }
  return { price, receipt };
}

function Summary({ invoice }: { invoice: InvoiceDetail }) {
  const c = invoice.field_confidence ?? {};
  const issues = lineIssues(invoice);
  return (
    <Card>
      <CardHeader
        title="Extracted data"
        description={
          invoice.extraction_method
            ? `${EXTRACTION_METHOD[invoice.extraction_method] ?? humanize(invoice.extraction_method)} · ${formatPercent(
                invoice.extraction_confidence,
                0,
              )} confidence`
            : "Waiting for extraction"
        }
      />
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-line px-5 py-4 sm:grid-cols-3">
        <Field label="Vendor" confidence={c.vendor_name}>
          {invoice.vendor ? (
            <Link to={`/invoices?vendor=${invoice.vendor.id}`} className="hover:underline">
              {invoice.vendor.name}
            </Link>
          ) : (
            invoice.vendor_name ?? "—"
          )}
        </Field>
        <Field label="Vendor ID">{invoice.vendor ? `ERP ${invoice.vendor.erp_id}` : "Not in master"}</Field>
        <Field label="GSTIN">{invoice.vendor_tax_id ?? "—"}</Field>
        <Field label="Invoice number" confidence={c.invoice_number}>
          {invoice.invoice_number ?? "—"}
        </Field>
        <Field label="Purchase order" confidence={invoice.po_number ? c.po_number : undefined}>
          {invoice.po_number ?? "—"}
        </Field>
        <Field label="Currency">{invoice.currency}</Field>
        <Field label="Invoice date" confidence={c.invoice_date}>
          {formatDate(invoice.invoice_date)}
        </Field>
        <Field label="Due date">{formatDate(invoice.due_date)}</Field>
        <Field label="Received">{formatDateTime(invoice.created_at)}</Field>
      </dl>
      <div className="border-t border-line px-5 py-3">
        <table className="w-full text-[13px]">
          <thead className="text-[12px] text-ink-3">
            <tr>
              <th className="pb-2 text-left font-medium">Line item</th>
              <th className="pb-2 pl-4 text-right font-medium whitespace-nowrap">Qty</th>
              <th className="pb-2 pl-4 text-right font-medium whitespace-nowrap">Unit price</th>
              <th className="pb-2 pl-4 text-right font-medium whitespace-nowrap">Amount</th>
              <th className="pb-2 pl-4 text-right font-medium whitespace-nowrap">PO item</th>
            </tr>
          </thead>
          <tbody className="tabular">
            {invoice.line_items.map((li) => {
              const priceIssue = issues.price.get(li.line_no);
              const openQty = li.po_item ? issues.receipt.get(li.po_item) : undefined;
              const flagged = Boolean(priceIssue || openQty);
              return (
                <tr key={li.line_no} className={clsx("border-t border-line", flagged && "bg-critical-soft")}>
                  <td className={clsx("py-2 pr-2 align-top text-ink", flagged && "pl-2")}>{li.description}</td>
                  <td className="py-2 pl-4 text-right align-top whitespace-nowrap text-ink-2">
                    {li.quantity}
                    {openQty && (
                      <div className="text-[11.5px] font-medium text-critical-ink">{openQty.replace(/\.0+$/, "")} received</div>
                    )}
                  </td>
                  <td className="py-2 pl-4 text-right align-top whitespace-nowrap text-ink-2">
                    {formatMoney(li.unit_price)}
                    {priceIssue && (
                      <div className="text-[11.5px] font-medium text-critical-ink">
                        PO {formatMoney(priceIssue.poPrice)} ({Number(priceIssue.variance) > 0 ? "+" : ""}
                        {priceIssue.variance}%)
                      </div>
                    )}
                  </td>
                  <td className="py-2 pl-4 text-right align-top whitespace-nowrap text-ink">{formatMoney(li.amount)}</td>
                  <td className={clsx("py-2 pl-4 text-right align-top whitespace-nowrap text-ink-3", flagged && "pr-2")}>{li.po_item ?? "—"}</td>
                </tr>
              );
            })}
            {invoice.line_items.length === 0 && (
              <tr>
                <td colSpan={5} className="py-3 text-ink-3">
                  No line items extracted.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot className="tabular border-t border-line-strong text-ink">
            <tr>
              <td colSpan={3} className="pt-2 text-right text-ink-2">
                Subtotal
              </td>
              <td className="pt-2 pl-4 text-right whitespace-nowrap">{formatMoney(invoice.subtotal)}</td>
            </tr>
            <tr>
              <td colSpan={3} className="text-right text-ink-2">
                Tax
              </td>
              <td className="pl-4 text-right whitespace-nowrap">{formatMoney(invoice.tax_amount)}</td>
            </tr>
            <tr className="font-semibold">
              <td colSpan={3} className="pt-1 text-right">
                Total
              </td>
              <td className="pt-1 pl-4 text-right whitespace-nowrap">{formatMoney(invoice.total_amount)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Card>
  );
}

export function InvoiceDetailPage() {
  const { id = "" } = useParams();
  const { data: invoice, error, isLoading, refetch } = useInvoice(id);
  const { data: meta } = useMeta();
  const { retry } = useDecision(id);
  const [decision, setDecision] = useState<"approve" | "reject" | null>(null);
  const threshold = meta?.anomaly_review_threshold ?? 0.5;

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-80" />
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <Skeleton className="h-[640px] rounded-xl" />
          <Skeleton className="h-[640px] rounded-xl" />
        </div>
      </div>
    );
  }
  if (error) {
    if (error instanceof ApiError && error.status === 404) {
      return <EmptyState icon={FileSearch} title="Invoice not found">It may have been removed, or the link is wrong.</EmptyState>;
    }
    return <ErrorState error={error} onRetry={() => void refetch()} />;
  }
  if (!invoice) return null;

  const processing = invoice.status === "received" || invoice.status === "processing";
  const can = (action: "approve" | "reject" | "retry") => invoice.allowed_actions.includes(action);

  return (
    <>
      <Link to="/invoices" className="mb-3 inline-flex items-center gap-1 text-[13px] text-ink-2 hover:text-ink">
        <ArrowLeft className="size-3.5" /> Invoices
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-[22px] leading-7 font-semibold tracking-[-0.01em] text-ink">
              {invoice.invoice_number ?? invoice.file_name}
            </h1>
            <StatusBadge status={invoice.status} />
          </div>
          <p className="mt-1 text-sm text-ink-2">
            {invoice.vendor?.name ?? invoice.vendor_name ?? "Vendor not yet identified"} ·{" "}
            <span className="tabular font-medium text-ink">{formatMoney(invoice.total_amount)}</span> · received{" "}
            {formatRelative(invoice.created_at)}
            {invoice.uploaded_by && <> by {invoice.uploaded_by.full_name}</>}
          </p>
        </div>
        <div className="flex gap-2">
          {can("reject") && (
            <Button variant="danger" icon={<X className="size-4" />} onClick={() => setDecision("reject")}>
              Reject
            </Button>
          )}
          {can("approve") && (
            <Button variant="primary" icon={<Check className="size-4" />} onClick={() => setDecision("approve")}>
              Approve
            </Button>
          )}
          {can("retry") && (
            <Button
              icon={<RotateCcw className="size-4" />}
              loading={retry.isPending}
              onClick={() =>
                retry.mutate(undefined, {
                  onSuccess: () => toast.success("Retry queued"),
                  onError: (e) => toast.error(e.message),
                })
              }
            >
              Retry {invoice.failure_stage === "posting" ? "posting" : "processing"}
            </Button>
          )}
        </div>
      </div>

      <div className="mb-4 space-y-3">
        {processing && (
          <Callout tone="info" icon={Loader2} title={STATUS[invoice.status].description}>
            Extraction, ERP matching and scoring usually finish within a few seconds. This page updates automatically.
          </Callout>
        )}
        {invoice.status === "needs_review" && (invoice.review_reasons?.length ?? 0) > 0 && (
          <Callout tone="warning" icon={TriangleAlert} title="Why this invoice needs review">
            <ul className="list-disc space-y-0.5 pl-4">
              {invoice.review_reasons?.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
            {invoice.status === "needs_review" && invoice.allowed_actions.length === 0 && (
              <p className="mt-2 text-ink-3">
                You can't decide on this invoice — an approver other than the uploader has to review it.
              </p>
            )}
          </Callout>
        )}
        {invoice.status === "failed" && (
          <Callout tone="critical" icon={OctagonAlert} title={`${humanize(invoice.failure_stage ?? "processing")} failed`}>
            {invoice.last_error}
          </Callout>
        )}
        {invoice.status === "posted" && (
          <Callout tone="good" icon={Check} title={`Posted to the ERP as document ${invoice.erp_document_number}`}>
            {invoice.auto_approved
              ? "Approved automatically: every check passed and the amount and risk were within policy."
              : `Approved by ${invoice.decided_by?.full_name ?? "an approver"} on ${formatDateTime(invoice.decided_at)}.`}
          </Callout>
        )}
        {invoice.status === "rejected" && (
          <Callout tone="neutral" icon={X} title={`Rejected by ${invoice.decided_by?.full_name ?? "an approver"}`}>
            {invoice.decision_comment}
          </Callout>
        )}
      </div>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div className="xl:sticky xl:top-6">
          <DocumentPreview invoiceId={invoice.id} fileName={invoice.file_name} />
        </div>
        <div className="space-y-4">
          {processing && !invoice.extraction_method ? (
            <Card className="grid h-48 place-items-center">
              <Spinner label="Reading the document" />
            </Card>
          ) : (
            <>
              <Summary invoice={invoice} />
              <div className="grid gap-4 2xl:grid-cols-2">
                <ChecksCard invoice={invoice} />
                <div className="space-y-4">
                  <RiskCard invoice={invoice} threshold={threshold} />
                  <Timeline invoice={invoice} />
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <DecisionDialog invoice={invoice} mode={decision} onClose={() => setDecision(null)} />
    </>
  );
}

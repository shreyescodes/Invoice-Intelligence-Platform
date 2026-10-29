import { ArrowRight, CircleCheck, Clock } from "lucide-react";
import { Link } from "react-router-dom";

import { RiskMeter } from "@/components/RiskMeter";
import { Card, PageHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { formatDate, formatMoney, formatRelative } from "@/lib/format";
import { useInvoices, useMeta } from "@/lib/queries";

export function ReviewQueuePage() {
  const { data: meta } = useMeta();
  const { data, error, isLoading, refetch } = useInvoices({ status: ["needs_review"], sort: "created_at", pageSize: 100 });

  return (
    <>
      <PageHeader
        title="Review queue"
        description={
          data
            ? `${data.total} invoice${data.total === 1 ? "" : "s"} could not be approved automatically. Oldest first.`
            : "Invoices that need an approver's decision."
        }
      />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && (
        <div className="space-y-3">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      )}
      {data && data.items.length === 0 && (
        <Card>
          <EmptyState icon={CircleCheck} title="All caught up">
            Every processed invoice has been approved or rejected.
          </EmptyState>
        </Card>
      )}
      <div className="space-y-3">
        {data?.items.map((invoice) => (
          <Card key={invoice.id} className="transition-colors hover:border-line-strong">
            <Link to={`/invoices/${invoice.id}`} className="flex flex-wrap items-start gap-x-6 gap-y-3 px-5 py-4">
              <div className="min-w-64 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[15px] font-semibold text-ink">
                    {invoice.vendor?.name ?? invoice.vendor_name ?? invoice.file_name}
                  </span>
                </div>
                <div className="mt-0.5 text-[13px] text-ink-3">
                  {invoice.invoice_number ?? "No invoice number"} · {invoice.po_number ? `PO ${invoice.po_number}` : "No PO"} ·
                  dated {formatDate(invoice.invoice_date)}
                </div>
                <ul className="mt-3 space-y-1">
                  {(invoice.review_reasons ?? []).slice(0, 3).map((reason) => (
                    <li key={reason} className="flex gap-2 text-[13px] text-ink-2">
                      <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-warning" aria-hidden />
                      {reason}
                    </li>
                  ))}
                  {(invoice.review_reasons?.length ?? 0) > 3 && (
                    <li className="pl-3.5 text-[12px] text-ink-3">+{(invoice.review_reasons?.length ?? 0) - 3} more</li>
                  )}
                </ul>
              </div>
              <div className="flex flex-col items-end gap-2">
                <span className="tabular text-[15px] font-semibold text-ink">{formatMoney(invoice.total_amount)}</span>
                <RiskMeter score={invoice.anomaly_score} threshold={meta?.anomaly_review_threshold} />
                <span className="inline-flex items-center gap-1 text-[12px] text-ink-3">
                  <Clock className="size-3.5" aria-hidden /> received {formatRelative(invoice.created_at)}
                </span>
                <span className="inline-flex items-center gap-1 text-[13px] font-medium text-accent-ink">
                  Review <ArrowRight className="size-3.5" />
                </span>
              </div>
            </Link>
          </Card>
        ))}
      </div>
    </>
  );
}

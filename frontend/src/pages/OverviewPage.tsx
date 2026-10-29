import { ArrowUpRight, CircleCheck, Inbox, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { BarList } from "@/components/charts/BarList";
import { SpendChart } from "@/components/charts/SpendChart";
import { RiskMeter } from "@/components/RiskMeter";
import { UploadDialog } from "@/components/UploadDialog";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, PageHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { Segmented } from "@/components/ui/Segmented";
import { useAuth } from "@/lib/auth-context";
import {
  formatHours,
  formatInteger,
  formatMoney,
  formatMoneyCompact,
  formatPercent,
  formatRelative,
} from "@/lib/format";
import { useInvoices, useMeta, useSummary } from "@/lib/queries";
import { CHECK_LABELS } from "@/lib/status";

const PERIODS = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "12 months" },
] as const;

function Kpi({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="text-[13px] text-ink-2">{label}</div>
      <div className="mt-1.5 text-[26px] leading-8 font-semibold tracking-[-0.015em] text-ink">{value}</div>
      {detail && <div className="mt-1 text-[12px] text-ink-3">{detail}</div>}
    </Card>
  );
}

function ReviewQueueCard() {
  const { data: meta } = useMeta();
  const { data, isLoading } = useInvoices({ status: ["needs_review", "failed"], sort: "created_at", pageSize: 6 });
  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Needs attention"
        description="Oldest first"
        action={
          <Link to="/review" className="inline-flex items-center gap-1 text-[13px] font-medium text-accent-ink hover:underline">
            Review queue <ArrowUpRight className="size-3.5" />
          </Link>
        }
      />
      {isLoading && (
        <div className="space-y-3 px-5 pb-5">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      )}
      {data && data.items.length === 0 && (
        <EmptyState icon={CircleCheck} title="Nothing waiting">Every invoice has been processed.</EmptyState>
      )}
      {data && data.items.length > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {data.items.map((invoice) => (
            <li key={invoice.id}>
              <Link to={`/invoices/${invoice.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-hover">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13px] font-medium text-ink">
                      {invoice.vendor?.name ?? invoice.vendor_name ?? invoice.file_name}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-[12px] text-ink-3">
                    {invoice.review_reasons?.[0] ?? invoice.invoice_number ?? "—"}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className="tabular text-[13px] font-medium text-ink">{formatMoneyCompact(invoice.total_amount)}</span>
                  {invoice.status === "failed" ? (
                    <StatusBadge status="failed" />
                  ) : (
                    <RiskMeter score={invoice.anomaly_score} threshold={meta?.anomaly_review_threshold} />
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function OverviewPage() {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]["value"]>("90");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [today] = useState(() =>
    new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" }),
  );
  const { hasRole } = useAuth();
  const { data, error, isLoading, isFetching, refetch } = useSummary(Number(period));
  const recent = useInvoices({ pageSize: 6 });

  const kpis = data?.kpis;

  return (
    <>
      <PageHeader
        eyebrow={today}
        title="Overview"
        description="How invoices are moving through capture, matching and approval."
        actions={
          hasRole("clerk", "approver", "admin") && (
            <Button variant="primary" icon={<Upload className="size-4" />} onClick={() => setUploadOpen(true)}>
              Upload invoices
            </Button>
          )
        }
      />

      <div className="mb-5">
        <Segmented label="Reporting period" value={period} onChange={setPeriod} options={[...PERIODS]} />
      </div>

      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      <div className={isFetching && !isLoading ? "opacity-70 transition-opacity" : "transition-opacity"}>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {isLoading || !kpis ? (
            Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[106px] rounded-xl" />)
          ) : (
            <>
              <Kpi
                label="Approved spend"
                value={formatMoneyCompact(kpis.spend_approved)}
                detail={`${formatInteger(kpis.invoices_processed)} invoices processed`}
              />
              <Kpi
                label="Straight-through rate"
                value={formatPercent(kpis.straight_through_rate)}
                detail="Approved with no human touch"
              />
              <Kpi label="Receipt to ERP posting" value={formatHours(kpis.avg_cycle_hours)} detail="Average cycle time" />
              <Kpi
                label="In review"
                value={formatInteger(kpis.review_queue_count)}
                detail={
                  kpis.review_queue_count
                    ? `${formatMoneyCompact(kpis.review_queue_value)} · oldest ${formatHours(kpis.oldest_review_hours)}`
                    : "Queue is clear"
                }
              />
            </>
          )}
        </div>

        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <Card className="flex flex-col xl:col-span-2">
            <CardHeader
              title="Approved spend by month"
              description="By invoice date, last 12 months"
              action={
                data && (
                  <span className="tabular text-right text-[13px] text-ink-2">
                    <span className="block text-[12px] text-ink-3">12-month total</span>
                    {formatMoney(
                      data.monthly_spend.reduce((sum, p) => sum + p.spend, 0),
                      { whole: true },
                    )}
                  </span>
                )
              }
            />
            <div className="min-h-72 flex-1 px-3 pb-4">
              {data ? <SpendChart data={data.monthly_spend} className="h-full min-h-72" /> : <Skeleton className="mx-2 h-72" />}
            </div>
          </Card>
          <ReviewQueueCard />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          <Card>
            <CardHeader title="Top vendors" description={`Approved spend, last ${PERIODS.find((p) => p.value === period)?.label}`} />
            <div className="px-5 pb-5">
              {data && data.top_vendors.length > 0 ? (
                <BarList
                  ariaLabel="Top vendors by approved spend"
                  items={data.top_vendors.map((v) => ({
                    key: v.name,
                    label: v.name,
                    value: v.value,
                    display: formatMoneyCompact(v.value),
                    hint: `${v.count} invoices`,
                  }))}
                />
              ) : (
                <p className="text-[13px] text-ink-3">No approved invoices in this period.</p>
              )}
            </div>
          </Card>
          <Card>
            <CardHeader title="Exceptions by rule" description="Failed or flagged checks" />
            <div className="px-5 pb-5">
              {data && data.exceptions.length > 0 ? (
                <BarList
                  ariaLabel="Exceptions by validation rule"
                  items={data.exceptions.map((e) => ({
                    key: e.name,
                    label: CHECK_LABELS[e.name] ?? e.name,
                    value: e.value,
                    display: formatInteger(e.count),
                  }))}
                />
              ) : (
                <p className="text-[13px] text-ink-3">No exceptions in this period.</p>
              )}
            </div>
          </Card>
          <Card className="lg:col-span-2 xl:col-span-1">
            <CardHeader
              title="Recent activity"
              action={
                <Link to="/invoices" className="text-[13px] font-medium text-accent-ink hover:underline">
                  All invoices
                </Link>
              }
            />
            {recent.data && recent.data.items.length === 0 && (
              <EmptyState icon={Inbox} title="No invoices yet">
                Upload a PDF to see it move through the pipeline.
              </EmptyState>
            )}
            <ul className="divide-y divide-line border-t border-line">
              {recent.data?.items.map((invoice) => (
                <li key={invoice.id}>
                  <Link to={`/invoices/${invoice.id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-hover">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium text-ink">
                        {invoice.invoice_number ?? invoice.file_name}
                      </div>
                      <div className="truncate text-[12px] text-ink-3">
                        {invoice.vendor?.name ?? invoice.vendor_name ?? "Reading document…"} · {formatRelative(invoice.created_at)}
                      </div>
                    </div>
                    <StatusBadge status={invoice.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </>
  );
}

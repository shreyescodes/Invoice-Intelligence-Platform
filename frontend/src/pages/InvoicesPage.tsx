import { ChevronLeft, ChevronRight, FileText, Search, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { RiskMeter } from "@/components/RiskMeter";
import { UploadDialog } from "@/components/UploadDialog";
import { StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { Input, Select } from "@/components/ui/Field";
import { Segmented } from "@/components/ui/Segmented";
import type { InvoiceStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { formatDate, formatMoney, formatRelative } from "@/lib/format";
import { useInvoices, useMeta, useVendors } from "@/lib/queries";

const TABS: { value: string; label: string; statuses: InvoiceStatus[] }[] = [
  { value: "all", label: "All", statuses: [] },
  { value: "review", label: "Needs review", statuses: ["needs_review"] },
  { value: "in-flight", label: "In progress", statuses: ["received", "processing", "approved"] },
  { value: "posted", label: "Posted", statuses: ["posted"] },
  { value: "rejected", label: "Rejected", statuses: ["rejected"] },
  { value: "failed", label: "Failed", statuses: ["failed"] },
];
const PAGE_SIZE = 20;

function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export function InvoicesPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const { data: meta } = useMeta();
  const vendors = useVendors();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search);

  const tab = TABS.find((t) => t.value === params.get("tab")) ?? TABS[0]!;
  const vendorId = params.get("vendor") ?? undefined;
  const page = Number(params.get("page") ?? "1") || 1;

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    if ((params.get("q") ?? "") !== q) setParam("q", q || null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only react to the debounced search text
  }, [q]);

  const { data, error, isLoading, isFetching, refetch } = useInvoices({
    status: tab.statuses,
    vendorId,
    q,
    page,
    pageSize: PAGE_SIZE,
  });
  const first = data && data.total ? (data.page - 1) * data.page_size + 1 : 0;
  const last = data ? Math.min(data.page * data.page_size, data.total) : 0;

  return (
    <>
      <PageHeader
        title="Invoices"
        description="Every document received, with its extraction, validation and approval state."
        actions={
          hasRole("clerk", "approver", "admin") && (
            <Button variant="primary" icon={<Upload className="size-4" />} onClick={() => setUploadOpen(true)}>
              Upload invoices
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented label="Status" value={tab.value} onChange={(v) => setParam("tab", v === "all" ? null : v)} options={TABS} />
        <div className="ml-auto flex flex-wrap gap-2">
          <Select
            aria-label="Vendor"
            value={vendorId ?? ""}
            onChange={(e) => setParam("vendor", e.target.value || null)}
            className="w-56"
          >
            <option value="">All vendors</option>
            {vendors.data?.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </Select>
          <Input
            aria-label="Search invoices"
            placeholder="Invoice no., vendor, PO…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            icon={<Search className="size-4" />}
            className="w-64"
          />
        </div>
      </div>

      {error && <ErrorState error={error} onRetry={() => void refetch()} />}

      <Card className={`overflow-hidden ${isFetching && !isLoading ? "opacity-80" : ""}`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-[13px]">
            <thead className="border-b border-line bg-surface-2 text-[12px] text-ink-3">
              <tr>
                <th className="px-5 py-2.5 font-medium">Invoice</th>
                <th className="px-3 py-2.5 font-medium">Vendor</th>
                <th className="px-3 py-2.5 font-medium">Invoice date</th>
                <th className="px-3 py-2.5 text-right font-medium">Amount</th>
                <th className="px-3 py-2.5 font-medium">Risk</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-5 py-2.5 text-right font-medium">Received</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {isLoading &&
                Array.from({ length: 8 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={7} className="px-5 py-3">
                      <Skeleton className="h-5" />
                    </td>
                  </tr>
                ))}
              {data?.items.map((invoice) => (
                <tr
                  key={invoice.id}
                  onClick={() => navigate(`/invoices/${invoice.id}`)}
                  className="cursor-pointer hover:bg-surface-hover"
                >
                  <td className="px-5 py-3">
                    <a
                      href={`/invoices/${invoice.id}`}
                      onClick={(e) => e.preventDefault()}
                      className="font-medium text-ink hover:underline"
                    >
                      {invoice.invoice_number ?? "Reading…"}
                    </a>
                    <div className="mt-0.5 max-w-56 truncate text-[12px] text-ink-3">{invoice.file_name}</div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="max-w-60 truncate text-ink">{invoice.vendor?.name ?? invoice.vendor_name ?? "—"}</div>
                    <div className="mt-0.5 text-[12px] text-ink-3">
                      {invoice.vendor ? `ERP ${invoice.vendor.erp_id}` : invoice.vendor_name ? "Not in vendor master" : ""}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-ink-2">{formatDate(invoice.invoice_date)}</td>
                  <td className="tabular px-3 py-3 text-right font-medium text-ink">{formatMoney(invoice.total_amount)}</td>
                  <td className="px-3 py-3">
                    <RiskMeter score={invoice.anomaly_score} threshold={meta?.anomaly_review_threshold} />
                  </td>
                  <td className="px-3 py-3">
                    <StatusBadge status={invoice.status} />
                  </td>
                  <td className="px-5 py-3 text-right text-ink-3">{formatRelative(invoice.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && data.items.length === 0 && (
          <EmptyState icon={FileText} title="No invoices match">
            Try another status or clear the search.
          </EmptyState>
        )}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between border-t border-line px-5 py-3 text-[13px] text-ink-2">
            <span className="tabular">
              {first}–{last} of {data.total}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                icon={<ChevronLeft className="size-4" />}
                disabled={page <= 1}
                onClick={() => setParam("page", String(page - 1))}
              >
                Previous
              </Button>
              <Button size="sm" disabled={last >= data.total} onClick={() => setParam("page", String(page + 1))}>
                Next <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </>
  );
}

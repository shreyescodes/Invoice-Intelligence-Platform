import { Building2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ToneBadge } from "@/components/ui/Badge";
import { Card, PageHeader } from "@/components/ui/Card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/Feedback";
import { formatDate, formatInteger, formatMoney, formatRelative } from "@/lib/format";
import { useVendors } from "@/lib/queries";

export function VendorsPage() {
  const { data, error, isLoading, refetch } = useVendors();
  const navigate = useNavigate();
  const lastSync = data?.reduce<string | null>((max, v) => (!max || v.synced_at > max ? v.synced_at : max), null);

  return (
    <>
      <PageHeader
        title="Vendors"
        description={
          <>
            Replicated from the ERP supplier master{lastSync ? `, last synced ${formatRelative(lastSync)}` : ""}. Invoices are
            matched to vendors by GSTIN.
          </>
        }
      />
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-[13px]">
            <thead className="border-b border-line bg-surface-2 text-[12px] text-ink-3">
              <tr>
                <th className="px-5 py-2.5 font-medium">Vendor</th>
                <th className="px-3 py-2.5 font-medium">GSTIN</th>
                <th className="px-3 py-2.5 font-medium">City</th>
                <th className="px-3 py-2.5 font-medium">Terms</th>
                <th className="px-3 py-2.5 text-right font-medium">Invoices</th>
                <th className="px-3 py-2.5 text-right font-medium">Open</th>
                <th className="px-3 py-2.5 text-right font-medium">Approved spend</th>
                <th className="px-5 py-2.5 text-right font-medium">Last invoice</th>
              </tr>
            </thead>
            <tbody className="tabular divide-y divide-line">
              {isLoading &&
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8} className="px-5 py-3">
                      <Skeleton className="h-5" />
                    </td>
                  </tr>
                ))}
              {data?.map((vendor) => (
                <tr
                  key={vendor.id}
                  className="cursor-pointer hover:bg-surface-hover"
                  onClick={() => navigate(`/invoices?vendor=${vendor.id}`)}
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2 font-medium text-ink">
                      {vendor.name}
                      {!vendor.is_active && <ToneBadge tone="neutral">Inactive</ToneBadge>}
                    </div>
                    <div className="mt-0.5 text-[12px] text-ink-3">ERP {vendor.erp_id}</div>
                  </td>
                  <td className="px-3 py-3 font-mono text-[12px] text-ink-2">{vendor.tax_id ?? "—"}</td>
                  <td className="px-3 py-3 text-ink-2">{vendor.city ?? "—"}</td>
                  <td className="px-3 py-3 text-ink-2">Net {vendor.payment_terms_days}</td>
                  <td className="px-3 py-3 text-right text-ink">{formatInteger(vendor.invoice_count)}</td>
                  <td className="px-3 py-3 text-right text-ink-2">{vendor.open_count || "—"}</td>
                  <td className="px-3 py-3 text-right font-medium text-ink">{formatMoney(vendor.total_spend, { whole: true })}</td>
                  <td className="px-5 py-3 text-right text-ink-2">{formatDate(vendor.last_invoice_date)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && data.length === 0 && (
          <EmptyState icon={Building2} title="No vendors yet">
            The worker replicates the supplier master from the ERP on start-up and every few minutes.
          </EmptyState>
        )}
      </Card>
    </>
  );
}

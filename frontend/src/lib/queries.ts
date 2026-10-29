import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap, uploadInvoice, type InvoiceStatus } from "./api";
import { PENDING_STATUSES } from "./status";

export interface InvoiceFilters {
  status?: InvoiceStatus[];
  vendorId?: string;
  q?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
}

export const keys = {
  meta: ["meta"] as const,
  invoices: (filters: InvoiceFilters) => ["invoices", filters] as const,
  invoice: (id: string) => ["invoice", id] as const,
  summary: (days: number) => ["summary", days] as const,
  vendors: ["vendors"] as const,
  suggestions: ["ask-suggestions"] as const,
};

export function useMeta() {
  return useQuery({
    queryKey: keys.meta,
    queryFn: () => unwrap(api.GET("/api/v1/meta")),
    staleTime: 5 * 60_000,
  });
}

export function useInvoices(filters: InvoiceFilters) {
  return useQuery({
    queryKey: keys.invoices(filters),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/invoices", {
          params: {
            query: {
              status: filters.status,
              vendor_id: filters.vendorId,
              q: filters.q || undefined,
              page: filters.page ?? 1,
              page_size: filters.pageSize ?? 25,
              sort: filters.sort ?? "-created_at",
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
    // Keep the list live while invoices are moving through the pipeline.
    refetchInterval: (query) =>
      query.state.data?.items.some((i) => PENDING_STATUSES.includes(i.status)) ? 2500 : false,
  });
}

export function useInvoice(id: string) {
  return useQuery({
    queryKey: keys.invoice(id),
    queryFn: () => unwrap(api.GET("/api/v1/invoices/{invoice_id}", { params: { path: { invoice_id: id } } })),
    refetchInterval: (query) => (query.state.data && PENDING_STATUSES.includes(query.state.data.status) ? 2000 : false),
  });
}

export function useSummary(days: number) {
  return useQuery({
    queryKey: keys.summary(days),
    queryFn: () => unwrap(api.GET("/api/v1/analytics/summary", { params: { query: { days } } })),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
}

export function useVendors() {
  return useQuery({ queryKey: keys.vendors, queryFn: () => unwrap(api.GET("/api/v1/vendors")) });
}

export function useSuggestions() {
  return useQuery({
    queryKey: keys.suggestions,
    queryFn: () => unwrap(api.GET("/api/v1/analytics/ask/suggestions")),
    staleTime: Infinity,
  });
}

export function useAsk() {
  return useMutation({
    mutationFn: (question: string) => unwrap(api.POST("/api/v1/analytics/ask", { body: { question } })),
  });
}

function useInvalidateInvoices() {
  const client = useQueryClient();
  return (id?: string) => {
    void client.invalidateQueries({ queryKey: ["invoices"] });
    void client.invalidateQueries({ queryKey: ["summary"] });
    if (id) void client.invalidateQueries({ queryKey: keys.invoice(id) });
  };
}

export function useUpload() {
  const invalidate = useInvalidateInvoices();
  return useMutation({ mutationFn: uploadInvoice, onSuccess: () => invalidate() });
}

export function useDecision(id: string) {
  const invalidate = useInvalidateInvoices();
  const client = useQueryClient();
  const onSuccess = (data: Awaited<ReturnType<typeof approve>>) => {
    client.setQueryData(keys.invoice(id), data);
    invalidate(id);
  };
  const approve = (comment: string | null) =>
    unwrap(api.POST("/api/v1/invoices/{invoice_id}/approve", { params: { path: { invoice_id: id } }, body: { comment } }));
  const reject = (comment: string) =>
    unwrap(api.POST("/api/v1/invoices/{invoice_id}/reject", { params: { path: { invoice_id: id } }, body: { comment } }));
  const retry = () => unwrap(api.POST("/api/v1/invoices/{invoice_id}/retry", { params: { path: { invoice_id: id } } }));
  return {
    approve: useMutation({ mutationFn: approve, onSuccess }),
    reject: useMutation({ mutationFn: reject, onSuccess }),
    retry: useMutation({ mutationFn: retry, onSuccess }),
  };
}

const BASE_URL = 'http://localhost:8000';

export interface InvoiceRecord {
  id: string;
  vendor_id?: string;
  vendor_name?: string; // added for UI convenience
  amount?: number;
  date?: string;
  status: string;
  anomaly_score?: number;
  anomaly_reason?: string;
  po_number?: string;
  tax_amount?: number;
  sap_match?: string;
}

export interface ChatQuery {
  question: string;
}

export interface ChatResponse {
  answer: string;
  sql_used?: string | null;
}

export interface ApprovalDecision {
  approve: boolean;
  reason?: string;
}

async function fetchApi(endpoint: string, options?: RequestInit) {
  try {
    const response = await fetch(`${BASE_URL}${endpoint}`, {
      ...options,
      headers: {
        ...(!(options?.body instanceof FormData) && { 'Content-Type': 'application/json' }),
        ...options?.headers,
      },
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`API Error ${response.status}: ${text}`);
    }
    return response.json();
  } catch (err) {
    console.error("API Call failed:", err);
    throw err;
  }
}

export const api = {
  uploadInvoice: async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return fetchApi('/invoices/upload', {
      method: 'POST',
      body: formData,
      headers: {} // Need to omit Content-Type for FormData so fetch sets the boundary
    });
  },
  
  getInvoices: async (status?: string, vendorId?: string) => {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (vendorId) params.append('vendor_id', vendorId);
    const qs = params.toString();
    return fetchApi(`/invoices${qs ? `?${qs}` : ''}`) as Promise<InvoiceRecord[]>;
  },

  getPendingApprovals: async () => {
    return fetchApi('/approvals/pending') as Promise<InvoiceRecord[]>;
  },

  submitDecision: async (invoiceId: string, decision: ApprovalDecision) => {
    return fetchApi(`/approvals/${invoiceId}/decide`, {
      method: 'POST',
      body: JSON.stringify(decision),
    });
  },

  askQuestion: async (query: ChatQuery) => {
    return fetchApi('/chat', {
      method: 'POST',
      body: JSON.stringify(query),
    }) as Promise<ChatResponse>;
  }
};

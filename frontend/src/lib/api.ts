import createClient, { type Middleware } from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type InvoiceStatus = Schemas["InvoiceListItem"]["status"];
export type InvoiceListItem = Schemas["InvoiceListItem"];
export type InvoiceDetail = Schemas["InvoiceDetail"];
export type InvoicePage = Schemas["InvoicePage"];
export type User = Schemas["UserOut"];
export type Meta = Schemas["MetaOut"];
export type Summary = Schemas["SummaryOut"];
export type Vendor = Schemas["VendorOut"];
export type AskResult = Schemas["AskOut"];
export type Role = User["role"];

/** An RFC 9457 problem returned by the API. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly extra: Record<string, unknown>;

  constructor(status: number, code: string, detail: string, extra: Record<string, unknown> = {}) {
    super(detail);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (accessToken) request.headers.set("Authorization", `Bearer ${accessToken}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401 && accessToken) onUnauthorized?.();
    return response;
  },
};

export const api = createClient<paths>({ baseUrl: "" });
api.use(authMiddleware);

async function toApiError(response: Response, body?: unknown): Promise<ApiError> {
  let problem = body as { detail?: unknown; code?: string; extra?: Record<string, unknown> } | undefined;
  if (problem === undefined) {
    try {
      problem = await response.clone().json();
    } catch {
      problem = undefined;
    }
  }
  const detail = typeof problem?.detail === "string" ? problem.detail : response.statusText || "Request failed";
  return new ApiError(response.status, problem?.code ?? "error", detail, problem?.extra ?? {});
}

/** Unwrap an openapi-fetch result, throwing an ApiError for non-2xx responses. */
export async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok || error !== undefined) throw await toApiError(response, error);
  return data as T;
}

async function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401 && accessToken) onUnauthorized?.();
  if (!response.ok) throw await toApiError(response);
  return response;
}

export async function login(email: string, password: string): Promise<Schemas["TokenOut"]> {
  const body = new URLSearchParams({ username: email, password, grant_type: "password" });
  const response = await rawFetch("/api/v1/auth/token", { method: "POST", body });
  return response.json();
}

export async function uploadInvoice(file: File): Promise<InvoiceListItem> {
  const form = new FormData();
  form.append("file", file);
  const response = await rawFetch("/api/v1/invoices", { method: "POST", body: form });
  return response.json();
}

export async function fetchPreview(invoiceId: string, page = 1): Promise<{ blob: Blob; pages: number }> {
  const response = await rawFetch(`/api/v1/invoices/${invoiceId}/preview?page=${page}`);
  return { blob: await response.blob(), pages: Number(response.headers.get("X-Page-Count") ?? "1") || 1 };
}

export async function fetchDocument(invoiceId: string): Promise<Blob> {
  const response = await rawFetch(`/api/v1/invoices/${invoiceId}/document`);
  return response.blob();
}

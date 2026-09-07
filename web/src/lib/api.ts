/** Typed client for the Receipt Tracker API.
 *  Same-origin in production (FastAPI serves the built SPA); Vite proxies /api in dev. */

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* a non-JSON error body is not worth failing over */
    }
    throw new ApiError(detail, response.status);
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// --- types (mirroring app/schemas/api.py) ---------------------------------
export type Money = string;

export interface SessionInfo { authenticated: boolean; subject: string | null }
export interface UploadResponse { id: string; status: string; duplicate: boolean }

export interface Item {
  id: string; line_no: number; raw_name: string;
  quantity: Money | null; unit: string | null; unit_price: Money | null;
  gross_amount: Money | null; discount_amount: Money | null;
  vat_rate: Money | null; vat_code: string | null; kind: string;
  product_id: string | null; category_id: string | null; confidence: number | null;
}

export interface ReceiptSummary {
  id: string; status: string; source: string; purchased_at: string | null;
  merchant_id: string | null; merchant_name: string | null;
  total_gross: Money | null; currency: string;
  review_reasons: string[] | null; confidence: number | null;
  item_count: number; created_at: string;
}

export interface ReceiptDetail extends ReceiptSummary {
  merchant_raw_name: string | null; tax_number: string | null;
  total_net: Money | null; total_vat: Money | null;
  rounding: Money | null; discount_total: Money | null;
  payment_method: string; receipt_no: string | null; nav_ap_code: string | null;
  notes: string | null; error: string | null; attempts: number;
  parsed_at: string | null; confirmed_at: string | null; items: Item[];
  pages: number;
}

export interface Category { id: string; parent_id: string | null; name: string; slug: string; color: string | null; sort_order: number }
export interface Merchant { id: string; name: string; slug: string; tax_number: string | null }
export interface Product { id: string; canonical_name: string; brand: string | null; category_id: string | null; package_size: number | null; package_unit: string | null }

export interface SpendSummary {
  total: Money; receipt_count: number; item_count: number; average_basket: Money;
  first_purchase: string | null; last_purchase: string | null; pending_review: number;
}
export interface MonthlySpend { month: string; total: Money; receipt_count: number }
export interface CategorySpend { category_id: string | null; category_name: string; total: Money; share: number; item_count: number }
export interface MerchantSpend { merchant_id: string | null; merchant_name: string; total: Money; receipt_count: number; average_basket: Money }
export interface PricePoint { purchased_at: string; merchant_id: string | null; merchant_name: string; unit_price: Money; quantity: Money | null; unit: string | null; receipt_id: string }
export interface PriceHistory { product_id: string; product_name: string; points: PricePoint[]; cheapest_merchant: string | null; latest_price: Money | null; change_pct: number | null }
export interface BasketMerchant { merchant_id: string; merchant_name: string; covered_products: number; basket_total: Money }
export interface BasketComparison { product_count: number; merchants: BasketMerchant[]; potential_saving: Money; window_days: number }
export interface InflationPoint { month: string; index: number; product_count: number }
export interface CostByMonth { month: string; model: string | null; receipts: number; total_usd: Money; avg_usd: Money; avg_input_tokens: number | null; avg_output_tokens: number | null }
export interface CostSummary { total_usd: Money; receipts_extracted: number; average_usd: Money; projected_yearly_usd: Money; by_month: CostByMonth[]; failures: number }
export interface Budget { id: string; category_id: string | null; month: string; amount: Money | null }

// Request bodies, not responses: money goes out as a plain number and pydantic converts it.
// `Money` is a string because that is how Decimal comes back, which is the wrong type here.
export interface SystemInfo {
  version: string;
  build: { commit: string | null; built_at: string | null; image: string | null };
  schema: { expected: string | null; applied: string | null; up_to_date: boolean };
  extractor: string; model: string | null; worker_enabled: boolean;
  max_image_edge: number; min_image_width: number;
  receipts: { total: number; pending: number; needs_review: number; failed: number };
}

export interface ManualItem {
  raw_name: string; gross_amount: number;
  quantity?: number | null; unit?: string | null; unit_price?: number | null; kind?: string;
}
export interface ManualReceipt {
  merchant_name: string; purchased_at: string; items: ManualItem[];
  total_gross?: number | null; payment_method?: string; notes?: string | null;
}
export interface Recurring {
  id: string; name: string; merchant_name: string; amount: Money; currency: string;
  cadence: string; day_of_month: number; month_of_year: number | null;
  payment_method: string; starts_on: string; ends_on: string | null; active: boolean;
  category_id: string | null; notes: string | null;
  charge_count: number; next_charge: string | null;
}

// --- endpoints -------------------------------------------------------------
export const api = {
  me: () => request<SessionInfo>("/api/auth/me"),
  login: (password: string) => request<SessionInfo>("/api/auth/login", json("POST", { password })),
  logout: () => request<SessionInfo>("/api/auth/logout", { method: "POST" }),

  upload(files: File | File[], onProgress?: (fraction: number) => void): Promise<UploadResponse> {
    // XHR rather than fetch: upload progress matters on a phone pushing a photo
    // over a VPN, and fetch still cannot report it.
    return new Promise((resolve, reject) => {
      const form = new FormData();
      // Several photos of one long receipt go up as repeats of the same field, in reading
      // order, and the server reads them as a single document.
      for (const file of Array.isArray(files) ? files : [files]) form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/receipts?source=web");
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as UploadResponse);
        } else {
          let detail = `Feltöltés sikertelen (${xhr.status})`;
          try { detail = JSON.parse(xhr.responseText).detail ?? detail; } catch { /* ignore */ }
          reject(new ApiError(detail, xhr.status));
        }
      };
      xhr.onerror = () => reject(new ApiError("Nem sikerült elérni a szervert.", 0));
      xhr.send(form);
    });
  },

  receipts: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
    );
    return request<ReceiptSummary[]>(`/api/receipts?${query}`);
  },
  receipt: (id: string) => request<ReceiptDetail>(`/api/receipts/${id}`),
  imageUrl: (id: string, part = 0) => `/api/receipts/${id}/image?part=${part}`,
  patchReceipt: (id: string, patch: Record<string, unknown>) =>
    request<ReceiptDetail>(`/api/receipts/${id}`, json("PATCH", patch)),
  confirm: (id: string) => request<ReceiptDetail>(`/api/receipts/${id}/confirm`, { method: "POST" }),
  reprocess: (id: string) => request<ReceiptDetail>(`/api/receipts/${id}/reprocess`, { method: "POST" }),
  remove: (id: string) => request<void>(`/api/receipts/${id}`, { method: "DELETE" }),
  patchItem: (id: string, patch: Record<string, unknown>) =>
    request<Item>(`/api/receipts/items/${id}`, json("PATCH", patch)),

  categories: () => request<Category[]>("/api/categories"),
  merchants: () => request<Merchant[]>("/api/merchants"),
  products: (q?: string) => request<Product[]>(`/api/products${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  trackedProducts: () => request<Product[]>("/api/products/tracked"),
  createProduct: (body: Record<string, unknown>, fromRawName?: string, merchantId?: string) => {
    const query = new URLSearchParams();
    if (fromRawName) query.set("from_raw_name", fromRawName);
    if (merchantId) query.set("merchant_id", merchantId);
    return request<Product>(`/api/products?${query}`, json("POST", body));
  },

  summary: () => request<SpendSummary>("/api/stats/summary"),
  monthly: () => request<MonthlySpend[]>("/api/stats/monthly"),
  byCategory: () => request<CategorySpend[]>("/api/stats/by-category"),
  byMerchant: () => request<MerchantSpend[]>("/api/stats/by-merchant"),
  priceHistory: (productId: string) => request<PriceHistory>(`/api/stats/price-history/${productId}`),
  basket: () => request<BasketComparison>("/api/stats/basket-comparison"),
  inflation: () => request<InflationPoint[]>("/api/stats/inflation"),

  costs: () => request<CostSummary>("/api/costs/summary"),
  createManual: (body: ManualReceipt) =>
    request<ReceiptDetail>("/api/receipts/manual", json("POST", body)),
  exportCsvUrl: () => "/api/receipts/export.csv",

  system: () => request<SystemInfo>("/api/system"),

  recurring: () => request<Recurring[]>("/api/recurring"),
  createRecurring: (body: Record<string, unknown>) =>
    request<Recurring>("/api/recurring", json("POST", body)),
  updateRecurring: (id: string, body: Record<string, unknown>) =>
    request<Recurring>(`/api/recurring/${id}`, json("PATCH", body)),
  deleteRecurring: (id: string) => request<void>(`/api/recurring/${id}`, { method: "DELETE" }),
  runRecurring: () => request<Recurring[]>("/api/recurring/run", { method: "POST" }),

  budgets: () => request<Budget[]>("/api/budgets"),
  putBudget: (body: Record<string, unknown>) => request<Budget>("/api/budgets", json("PUT", body)),
};

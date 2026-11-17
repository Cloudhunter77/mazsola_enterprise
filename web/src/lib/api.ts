/** Typed client for the Receipt Tracker API.
 *  Same-origin in production (FastAPI serves the built SPA); Vite proxies /api in dev. */

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "same-origin", ...init });
  } catch {
    // fetch rejects with a bare `TypeError: Failed to fetch` for anything below HTTP:
    // a dropped VPN, a sleeping phone, a container restart. Status 0 marks it as
    // "the request never arrived", which is retryable - unlike a 4xx, which will
    // say the same thing however many times you ask. The upload path already uses
    // 0 for the same meaning.
    throw new ApiError("Nem sikerült elérni a szervert.", 0);
  }

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

export interface FixNote {
  id: string; text: string; has_image: boolean; created_by: string | null;
  created_at: string; done: boolean; done_at: string | null;
}
export interface SessionInfo {
  authenticated: boolean; subject: string | null;
  user_id: string | null; display_name: string | null; is_admin: boolean;
}
export interface User {
  id: string; username: string; display_name: string; is_admin: boolean; active: boolean;
  is_me: boolean;
}
export interface UploadResponse { id: string; status: string; duplicate: boolean }

export interface Item {
  id: string; line_no: number; raw_name: string;
  quantity: Money | null; unit: string | null; unit_price: Money | null;
  gross_amount: Money | null; discount_amount: Money | null;
  vat_rate: Money | null; vat_code: string | null; kind: string;
  product_id: string | null; category_id: string | null; confidence: number | null;
  // Which rule filed it, or "manual" when you did.
  category_source: string | null;
  // The goal or pocket line it was bought for, and the wishlist item it was.
  earmark_id?: string | null; wishlist_item_id?: string | null;
}

export interface ReceiptSummary {
  id: string; status: string; source: string; purchased_at: string | null;
  merchant_id: string | null; merchant_name: string | null;
  total_gross: Money | null; currency: string;
  review_reasons: string[] | null; confidence: number | null;
  item_count: number; created_at: string; paid_by_id: string | null;
}

export interface Share { user_id: string; percent: Money; amount: Money }

export interface ReceiptDetail extends ReceiptSummary {
  merchant_raw_name: string | null; tax_number: string | null;
  total_net: Money | null; total_vat: Money | null;
  rounding: Money | null; discount_total: Money | null;
  payment_method: string; receipt_no: string | null; nav_ap_code: string | null;
  notes: string | null; error: string | null; attempts: number;
  parsed_at: string | null; confirmed_at: string | null; items: Item[];
  pages: number; uploaded_by_id: string | null;
  // Empty when the bill is not split.
  shares: Share[];
  // Chosen ("manual"; null pocket = the main account), or only guessed from the categories.
  pocket_id: string | null; pocket_source: string | null; pocket_guess: string | null;
}

export interface SplitReceipt {
  receipt_id: string; purchased_at: string | null; merchant_name: string | null;
  total_gross: Money | null; paid_by_id: string | null; shares: Share[];
}
export interface Transfer {
  from_user_id: string; from_name: string; to_user_id: string; to_name: string; amount: Money;
}
export interface Settlement extends Transfer { id: string; settled_at: string; note: string | null }
export interface SplitSummary {
  balances: { user_id: string; display_name: string; net: Money }[];
  transfers: Transfer[]; receipts: SplitReceipt[]; settlements: Settlement[];
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
// A price point is either something you bought or something you photographed on a shelf, and
// the two are not interchangeable: a shelf price is what the shop asks, a purchase price is
// what you paid. `receipt_id` is null on the former, `observation_id` on the latter.
export interface PricePoint {
  purchased_at: string; merchant_id: string | null; merchant_name: string;
  unit_price: Money; quantity: Money | null; unit: string | null;
  source: "purchase" | "label"; is_promotion: boolean;
  receipt_id: string | null; observation_id: string | null; label_photo_id: string | null;
}
export interface PriceHistory { product_id: string; product_name: string; points: PricePoint[]; cheapest_merchant: string | null; latest_price: Money | null; change_pct: number | null }
export interface BasketMerchant { merchant_id: string; merchant_name: string; covered_products: number; basket_total: Money }
export interface BasketComparison { product_count: number; merchants: BasketMerchant[]; potential_saving: Money; window_days: number }
export interface InflationPoint { month: string; index: number; product_count: number }
// `kind` is what the engine was reading: a receipt, a shelf label or a product photograph.
// Three documents of very different shapes, so three different bills.
export type AttemptKind = "receipt" | "price_label" | "product_photo";
export interface CostByMonth { month: string; kind: AttemptKind; model: string | null; calls: number; total_usd: Money; avg_usd: Money; avg_input_tokens: number | null; avg_output_tokens: number | null }
export interface CostByKind { kind: AttemptKind; calls: number; total_usd: Money; avg_usd: Money; avg_input_tokens: number | null; avg_output_tokens: number | null; failures: number }
export interface CostSummary { total_usd: Money; calls: number; average_usd: Money; projected_yearly_usd: Money; by_kind: CostByKind[]; by_month: CostByMonth[]; failures: number }

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

export interface Suggestion {
  suggested_name: string; members: string[]; occurrences: number;
  score: number; band: "green" | "yellow" | "red"; total_spent: Money;
  product_id: string | null; product_name: string | null;
  product_members: string[]; member_occurrences: Record<string, number>;
  member_prices: Record<string, Money>;
}
export interface ReceiptToFile {
  receipt_id: string; purchased_at: string | null; total_gross: Money | null;
  merchant_id: string | null; merchant_name: string | null; shop_default_id: string | null;
  uncategorised_lines: number; uncategorised_amount: Money; item_lines: number; names: string[];
}
export interface ReceiptFiling {
  category_id: string; item_ids: string[]; lines: number; spread: number;
  merchant_id: string | null; previous_default: string | null;
}
export interface Suggestions { unmapped_lines: number; groups: Suggestion[] }

export interface ManualItem {
  raw_name: string; gross_amount: number;
  quantity?: number | null; unit?: string | null; unit_price?: number | null; kind?: string;
}
export interface ManualReceipt {
  merchant_name: string; purchased_at: string; items: ManualItem[];
  total_gross?: number | null; payment_method?: string; notes?: string | null;
  pocket_id?: string | null;
}
export interface Recurring {
  id: string; name: string; merchant_name: string; amount: Money; currency: string;
  cadence: string; day_of_month: number; month_of_year: number | null;
  payment_method: string; starts_on: string; ends_on: string | null; active: boolean;
  category_id: string | null; notes: string | null;
  direction: "expense" | "income"; amount_mode: "fixed" | "variable";
  // null is Közös.
  owner_id: string | null; payer_id: string | null;
  default_shares: { user_id: string; percent: Money }[] | null;
  pocket_id: string | null;
  charge_count: number; next_charge: string | null;
}

// --- budgeting (mirroring app/schemas/budget.py) ------------------------------
/** Fix / Változó / Célalap / Megtakarítás - the spreadsheet's "Csoport". */
export type LineKind = "fix" | "valtozo" | "celalap" | "megtakaritas";
export interface Person { id: string; display_name: string; active: boolean }
export interface Period {
  id: string; month: string; starts_on: string;
  /** Exclusive: the day the next period began. Null for the current one. */
  ends_on: string | null;
  closed_at: string | null; is_current: boolean;
}
export interface BudgetStatus {
  meeting_due: boolean; current: Period | null; today: string;
  suggested_starts_on: string; suggested_month: string;
}
export interface BudgetLine {
  id: string; name: string; owner_id: string | null; kind: LineKind;
  category_ids: string[]; active: boolean; sort_order: number; notes: string | null;
  pocket_id: string | null; target_amount: Money | null; target_date: string | null;
  is_wishlist: boolean; bought_on: string | null;
}
export interface PlanCell { amount: Money; explicit: boolean }
export interface PlanRow {
  key: string; type: "line" | "recurring" | "income"; id: string; name: string;
  owner_id: string | null; kind: LineKind; active: boolean; category_ids: string[];
  yearly: boolean; cells: PlanCell[];
  pocket_id: string | null; target_amount: Money | null; target_date: string | null;
  suggestion: Money | null;
}
export interface PlanMonth { month: string; period_id: string | null; locked: boolean }
export interface PersonTotals { user_id: string; income: Money; planned: Money; free: Money }
export interface PlanTotals { income: Money; planned: Money; free: Money; people: PersonTotals[] }
export interface Plan { months: PlanMonth[]; rows: PlanRow[]; totals: PlanTotals[]; users: Person[] }
export interface Income {
  id: string; user_id: string | null; name: string; amount: Money; received_on: string;
  recurring_id: string | null; notes: string | null; created_at: string;
}
export type OccurrenceStatus = "expected" | "due" | "done" | "skipped";
export interface Occurrence {
  recurring_id: string; name: string; direction: "expense" | "income";
  amount_mode: "fixed" | "variable"; owner_id: string | null;
  month: string; due: string; status: OccurrenceStatus;
  expected_amount: Money; amount: Money | null; booked_on: string | null;
  receipt_id: string | null; income_id: string | null;
}
export interface Piece {
  receipt_id: string; day: string; merchant: string | null; amount: Money;
  category_id?: string | null;
}
export interface MonthRow {
  key: string; type: "line" | "recurring" | "unplanned"; id: string | null; name: string;
  owner_id: string | null; kind: LineKind; plan: Money;
  /** Null for money set aside, which no receipt shows. */
  actual: Money | null;
  yearly: boolean; active: boolean; category_ids: string[]; receipts: Piece[];
}
export interface MonthView {
  period: Period; periods: Period[]; users: Person[]; rows: MonthRow[];
  income: { owner_id: string | null; arrived: Money; expected: Money }[];
  income_entries: Income[]; occurrences: Occurrence[];
  issues: {
    due: Occurrence[]; uncategorised: Piece[]; maybe_shared: Piece[];
    late: (Piece & { period_month: string })[];
    maybe_pocket: Piece[]; transfers: PocketTransfer[];
  };
  pockets: PocketView[];
  totals: {
    planned_spending: Money; planned_aside: Money; spent: Money;
    income_arrived: Money; income_expected: Money; free: Money;
  };
  meeting_due: boolean; receipt_count: number;
}

// --- pockets and the wishlist ------------------------------------------------
export interface Pocket {
  id: string; name: string; holder_id: string | null; opening_balance: Money;
  opened_on: string; active: boolean; notes: string | null;
}
/** One earmark of a pocket, or (line_id null) the money no earmark claims. */
export interface Bucket {
  line_id: string | null; name: string; owner_id: string | null; kind: LineKind | null;
  is_wishlist: boolean; target_amount: Money | null; target_date: string | null;
  bought_on: string | null; category_ids: string[];
  plan: Money; opening: Money; money_in: Money; money_out: Money; closing: Money;
  suggestion: Money | null; receipts: Piece[];
}
export interface PocketView {
  pocket: Pocket; opening: Money; closing: Money; buckets: Bucket[];
  check: { checked_on: string; balance: Money; expected: Money; difference: Money } | null;
}
export interface PocketTransfer {
  id: string; pocket_id: string; pocket_name: string; holder_id: string | null;
  line_id: string | null; line_name: string | null; amount: Money; on: string;
  kind: string; done: boolean; from_user_id: string | null; note: string | null;
}
export interface PocketsOverview {
  users: Person[]; start: string; month: string; pockets: PocketView[];
  pending: PocketTransfer[];
}
export interface ProposedTransfer {
  line_id: string; line_name: string; pocket_id: string; pocket_name: string;
  holder_id: string | null; from_user_id: string | null; amount: Money;
}
export interface Wish {
  id: string; owner_id: string | null; name: string; priority: number;
  priority_label: string; estimated_price: Money | null; link: string | null;
  note: string | null; product_id: string | null; product_name: string | null;
  on_list: boolean; bought_on: string | null; actual_price: Money | null;
  receipt_ids: string[]; earmark_id: string | null;
}

export interface CategoryLine {
  item_id: string; raw_name: string; quantity: Money | null; unit: string | null;
  gross_amount: Money; receipt_id: string; purchased_at: string | null; status: string;
  merchant_name: string | null;
}
export interface MerchantReceipt {
  receipt_id: string; purchased_at: string | null; total_gross: Money; status: string;
}

// --- endpoints -------------------------------------------------------------
export type LabelUploadResponse = { id: string; status: string; duplicate: boolean };

export type Observation = {
  id: string;
  line_no: number;
  raw_name: string;
  product_id: string | null;
  product_name: string | null;
  price: Money | null;
  unit_price: Money | null;
  unit: string | null;
  package_size: number | null;
  package_unit: string | null;
  is_promotion: boolean;
  regular_price: Money | null;
  promotion_until: string | null;
  confidence: number | null;
};

export type ScannedPrice = {
  id: string;
  photo_id: string;
  observed_at: string;
  merchant_name: string | null;
  raw_name: string;
  product_id: string | null;
  product_name: string | null;
  price: Money | null;
  unit_price: Money | null;
  unit: string | null;
  is_promotion: boolean;
  regular_price: Money | null;
  confidence: number | null;
};

export type ShoppingItem = {
  id: string;
  product_id: string | null;
  product_name: string | null;
  raw_name: string | null;
  label: string;
  has_photo: boolean;
  quantity: string | null;
  note: string | null;
  source: string;
  status: string;
  confidence: number | null;
  error: string | null;
  done: boolean;
  done_at: string | null;
  created_at: string;
};

export type ShoppingSuggestion = { product_id: string; canonical_name: string };

export type LabelPhoto = {
  id: string;
  status: string;
  observed_at: string;
  merchant_name: string | null;
  observation_count: number;
  review_reasons: string[];
  error: string | null;
};

export type LabelPhotoDetail = Omit<LabelPhoto, "observation_count"> & {
  notes: string | null;
  confidence: number | null;
  observations: Observation[];
};

export const api = {
  me: () => request<SessionInfo>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<SessionInfo>("/api/auth/login", json("POST", { username: username || null, password })),
  users: () => request<User[]>("/api/users"),
  fixNotes: () => request<FixNote[]>("/api/fixes"),
  addFixNote: (text: string, image: File | null) => {
    const form = new FormData();
    form.append("text", text);
    if (image) form.append("image", image);
    return request<FixNote>("/api/fixes", { method: "POST", body: form });
  },
  updateFixNote: (id: string, body: { done?: boolean; text?: string }) =>
    request<FixNote>(`/api/fixes/${id}`, json("PATCH", body)),
  deleteFixNote: (id: string) => request<void>(`/api/fixes/${id}`, { method: "DELETE" }),
  fixNoteImageUrl: (id: string) => `/api/fixes/${id}/image`,
  createUser: (body: { username: string; display_name: string; password: string; is_admin: boolean }) =>
    request<User>("/api/users", json("POST", body)),
  updateUser: (id: string, body: Partial<{
    display_name: string; username: string; password: string; current_password: string;
    is_admin: boolean; active: boolean;
  }>) => request<User>(`/api/users/${id}`, json("PATCH", body)),
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

  uploadLabel(
    file: File,
    shop: string | null,
    onProgress?: (fraction: number) => void,
  ): Promise<LabelUploadResponse> {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      const query = shop ? `?shop=${encodeURIComponent(shop)}` : "";
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/labels${query}`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as LabelUploadResponse);
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

  shoppingList: () => request<ShoppingItem[]>("/api/shopping"),
  shoppingSuggestions: () =>
    request<ShoppingSuggestion[]>("/api/shopping/suggestions"),
  addToList: (body: Record<string, unknown>) =>
    request<ShoppingItem>("/api/shopping", json("POST", body)),
  updateListItem: (id: string, patch: Record<string, unknown>) =>
    request<ShoppingItem>(`/api/shopping/${id}`, json("PATCH", patch)),
  deleteListItem: (id: string) =>
    request<void>(`/api/shopping/${id}`, { method: "DELETE" }),
  clearDone: () =>
    request<{ removed: number }>("/api/shopping/clear-done", { method: "POST" }),
  listItemImageUrl: (id: string) => `/api/shopping/${id}/image`,

  scanOntoList(file: File, onProgress?: (fraction: number) => void): Promise<ShoppingItem> {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/shopping/scan");
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as ShoppingItem);
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

  scannedPrices: (limit = 200) =>
    request<ScannedPrice[]>(`/api/labels/prices?limit=${limit}`),
  labelPhotos: (limit = 50) => request<LabelPhoto[]>(`/api/labels?limit=${limit}`),
  labelPhoto: (id: string) => request<LabelPhotoDetail>(`/api/labels/${id}`),
  labelImageUrl: (id: string) => `/api/labels/${id}/image`,
  patchObservation: (id: string, patch: Record<string, unknown>) =>
    request<Observation>(`/api/labels/observations/${id}`, json("PATCH", patch)),
  deleteObservation: (id: string) =>
    request<void>(`/api/labels/observations/${id}`, { method: "DELETE" }),
  confirmLabelPhoto: (id: string) =>
    request<LabelPhotoDetail>(`/api/labels/${id}/confirm`, { method: "POST" }),
  deleteLabelPhoto: (id: string) => request<void>(`/api/labels/${id}`, { method: "DELETE" }),

  receipts: (params: Record<string, string | number | undefined> = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]),
    );
    return request<ReceiptSummary[]>(`/api/receipts?${query}`);
  },
  receipt: (id: string) => request<ReceiptDetail>(`/api/receipts/${id}`),
  splitReceipt: (id: string, paid_by_id: string | null, shares: { user_id: string; percent: number }[]) =>
    request<ReceiptDetail>(`/api/receipts/${id}/split`, json("PUT", { paid_by_id, shares })),
  splitSummary: () => request<SplitSummary>("/api/split/summary"),
  settle: (from_user_id: string, to_user_id: string, amount: number, note?: string) =>
    request<Settlement>("/api/split/settlements", json("POST", { from_user_id, to_user_id, amount, note })),
  deleteSettlement: (id: string) =>
    request<void>(`/api/split/settlements/${id}`, { method: "DELETE" }),
  latestReceipt: () =>
    request<ReceiptSummary[]>("/api/receipts?limit=1").then((rows) => rows[0] ?? null),
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
  categoryLines: (categoryId: string | null) =>
    request<CategoryLine[]>(`/api/stats/category-lines?category_id=${categoryId ?? "none"}`),
  merchantReceipts: (merchantId: string | null) =>
    request<MerchantReceipt[]>(`/api/stats/merchant-receipts?merchant_id=${merchantId ?? "none"}`),
  priceHistory: (productId: string) => request<PriceHistory>(`/api/stats/price-history/${productId}`),
  basket: () => request<BasketComparison>("/api/stats/basket-comparison"),
  inflation: () => request<InflationPoint[]>("/api/stats/inflation"),

  costs: () => request<CostSummary>("/api/costs/summary"),
  createManual: (body: ManualReceipt) =>
    request<ReceiptDetail>("/api/receipts/manual", json("POST", body)),
  exportCsvUrl: () => "/api/receipts/export.csv",

  system: () => request<SystemInfo>("/api/system"),

  suggestions: () => request<Suggestions>("/api/suggestions"),
  receiptsToFile: () => request<ReceiptToFile[]>("/api/categorise/receipts"),
  fileReceipt: (receipt_id: string, category_id: string, remember_shop: boolean, replace_guesses = false) =>
    request<ReceiptFiling>("/api/categorise/receipt", json("POST", {
      receipt_id, category_id, remember_shop, replace_guesses,
    })),
  undoFiling: (done: ReceiptFiling) =>
    request<{ reverted: number }>("/api/categorise/undo", json("POST", {
      category_id: done.category_id, item_ids: done.item_ids,
      merchant_id: done.merchant_id, previous_default: done.previous_default,
    })),
  applySuggestion: (body: Record<string, unknown>) =>
    request<Product>("/api/suggestions/apply", json("POST", body)),
  autolink: () =>
    request<{
      linked: number;
      created: number;
      categorised: number;
      by_rule: Record<string, number>;
    }>("/api/suggestions/autolink", { method: "POST" }),

  recurring: () => request<Recurring[]>("/api/recurring"),
  createRecurring: (body: Record<string, unknown>) =>
    request<Recurring>("/api/recurring", json("POST", body)),
  updateRecurring: (id: string, body: Record<string, unknown>) =>
    request<Recurring>(`/api/recurring/${id}`, json("PATCH", body)),
  deleteRecurring: (id: string) => request<void>(`/api/recurring/${id}`, { method: "DELETE" }),
  runRecurring: () => request<Recurring[]>("/api/recurring/run", { method: "POST" }),
  occurrences: (periodId?: string) =>
    request<Occurrence[]>(`/api/recurring/occurrences${periodId ? `?period_id=${periodId}` : ""}`),
  confirmOccurrence: (id: string, body: { month: string; amount: number; on?: string }) =>
    request<void>(`/api/recurring/${id}/occurrences`, json("POST", body)),
  skipOccurrence: (id: string, month: string) =>
    request<void>(`/api/recurring/${id}/occurrences/skip`, json("POST", { month })),
  undoOccurrence: (id: string, month: string) =>
    request<void>(`/api/recurring/${id}/occurrences/${month}`, { method: "DELETE" }),

  budgetStatus: () => request<BudgetStatus>("/api/budget/status"),
  periods: () => request<Period[]>("/api/budget/periods"),
  openPeriod: (body: {
    starts_on?: string; month?: string;
    transfers?: { line_id: string; from_user_id: string | null; amount: number; done: boolean }[];
    checks?: { pocket_id: string; balance: number }[];
  }) =>
    request<Period>("/api/budget/periods", json("POST", body)),
  reopenPeriod: (id: string) =>
    request<Period>(`/api/budget/periods/${id}/reopen`, { method: "POST" }),
  closePeriod: (id: string) =>
    request<Period>(`/api/budget/periods/${id}/close`, { method: "POST" }),
  budgetMonth: (periodId?: string) =>
    request<MonthView>(`/api/budget/month${periodId ? `?period_id=${periodId}` : ""}`),
  plan: (start?: string, months = 6) =>
    request<Plan>(`/api/budget/plan?months=${months}${start ? `&start=${start}` : ""}`),
  setPlanAmount: (line_id: string, month: string, amount: number | null) =>
    request<void>("/api/budget/plan", json("PUT", { line_id, month, amount })),
  budgetLines: () => request<BudgetLine[]>("/api/budget/lines"),
  createLine: (body: Record<string, unknown>) =>
    request<BudgetLine>("/api/budget/lines", json("POST", body)),
  updateLine: (id: string, body: Record<string, unknown>) =>
    request<BudgetLine>(`/api/budget/lines/${id}`, json("PATCH", body)),
  removeLine: (id: string) =>
    request<{ deleted: boolean }>(`/api/budget/lines/${id}`, { method: "DELETE" }),

  goalBought: (id: string, body: { move_to_line_id?: string | null; release?: boolean }) =>
    request<BudgetLine>(`/api/budget/lines/${id}/bought`, json("POST", body)),

  pockets: () => request<Pocket[]>("/api/pockets"),
  pocketsOverview: () => request<PocketsOverview>("/api/pockets/overview"),
  createPocket: (body: Record<string, unknown>) =>
    request<Pocket>("/api/pockets", json("POST", body)),
  updatePocket: (id: string, body: Record<string, unknown>) =>
    request<Pocket>(`/api/pockets/${id}`, json("PATCH", body)),
  deletePocket: (id: string) => request<void>(`/api/pockets/${id}`, { method: "DELETE" }),
  pocketCheck: (pocket_id: string, balance: number) =>
    request<void>("/api/pockets/checks", json("POST", { pocket_id, balance })),
  proposedTransfers: (month: string) =>
    request<ProposedTransfer[]>(`/api/pockets/proposed?month=${month}`),
  pocketTransfer: (body: { pocket_id: string; line_id: string | null; amount: number; note?: string }) =>
    request<{ id: string }>("/api/pockets/transfers", json("POST", body)),
  pocketMove: (body: { pocket_id: string; from_line_id: string | null; to_line_id: string | null; amount: number }) =>
    request<void>("/api/pockets/moves", json("POST", body)),
  transferDone: (id: string, done = true) =>
    request<void>(`/api/pockets/transfers/${id}`, json("PATCH", { done })),
  deleteTransfer: (id: string) =>
    request<void>(`/api/pockets/transfers/${id}`, { method: "DELETE" }),
  purchase: (body: Record<string, unknown>) =>
    request<{ receipt_id: string }>("/api/pockets/purchase", json("POST", body)),
  setReceiptPocket: (id: string, body: { pocket_id?: string | null; auto?: boolean }) =>
    request<ReceiptDetail>(`/api/receipts/${id}/pocket`, json("PUT", body)),
  linkLines: (id: string, body: { item_ids: string[]; earmark_id?: string | null; wishlist_item_id?: string | null }) =>
    request<ReceiptDetail>(`/api/receipts/${id}/links`, json("PUT", body)),

  wishlist: () => request<Wish[]>("/api/wishlist"),
  addWish: (body: Record<string, unknown>) => request<Wish>("/api/wishlist", json("POST", body)),
  updateWish: (id: string, body: Record<string, unknown>) =>
    request<Wish>(`/api/wishlist/${id}`, json("PATCH", body)),
  deleteWish: (id: string) => request<void>(`/api/wishlist/${id}`, { method: "DELETE" }),
  wishToList: (id: string) => request<Wish>(`/api/wishlist/${id}/to-list`, { method: "POST" }),
  reopenWish: (id: string) => request<Wish>(`/api/wishlist/${id}/reopen`, { method: "POST" }),

  income: () => request<Income[]>("/api/income"),
  addIncome: (body: { user_id: string | null; name: string; amount: number; received_on: string; notes?: string }) =>
    request<Income>("/api/income", json("POST", body)),
  deleteIncome: (id: string) => request<void>(`/api/income/${id}`, { method: "DELETE" }),
};

/** Typed client for the Leltár API.
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
    // fetch rejects with a bare `TypeError: Failed to fetch` for anything below HTTP: a
    // dropped VPN, a sleeping phone, a container restart. Status 0 marks it as "the
    // request never arrived", which is retryable - unlike a 4xx, which will say the same
    // thing however many times you ask.
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

// --- types (mirroring leltar/schemas/api.py) --------------------------------
export type Money = string;

export interface SessionInfo { authenticated: boolean; subject: string | null }

export interface UploadedPhoto { id: string; status: string; duplicate: boolean }
export interface UploadResponse { photos: UploadedPhoto[]; queued: number; duplicates: number }

export interface Place {
  id: string; parent_id: string | null; name: string; kind: string;
  sort_order: number; notes: string | null; path: string; item_count: number;
}

export interface Category {
  id: string; slug: string; name: string; icon: string | null; sort_order: number;
}

export interface Item {
  id: string; photo_id: string | null; place_id: string | null; category_id: string | null;
  name: string; suggested_name: string | null;
  brand: string | null; product_model: string | null;
  colour: string | null; material: string | null; condition: string; quantity: number;
  serial_number: string | null; description: string | null;
  value: Money | null; currency: string; acquired_on: string | null;
  status: string; source: string; edited: boolean; confidence: number | null;
  review_reasons: string[] | null; alternatives: string[] | null;
  notes: string | null; confirmed_at: string | null; created_at: string;
  place_path: string | null; category_name: string | null; image_count: number;
}

export interface ItemImage {
  id: string; item_id: string; kind: string; source_photo_id: string | null;
  box: { x0: number; y0: number; x1: number; y1: number } | null;
  width: number | null; height: number | null; is_primary: boolean; created_at: string;
}

export interface Photo {
  id: string; status: string; source: string; mode: string; place_id: string | null;
  taken_at: string | null; scene: string | null; confidence: number | null;
  review_reasons: string[] | null; error: string | null; attempts: number;
  created_at: string; place_path: string | null; item_count: number; draft_count: number;
}

export interface PhotoDetail extends Photo { notes: string | null; items: Item[] }

export interface StatsSummary {
  items: number; copies: number; places_used: number; categories_used: number;
  with_picture: number; drafts: number;
  photos: number; photos_pending: number; photos_needing_review: number;
  photos_failed: number; last_added: string | null;
}
export interface PlaceStat {
  place_id: string | null; place_path: string; items: number; copies: number; share: number;
}
export interface CategoryStat {
  category_id: string | null; category_name: string; icon: string | null;
  items: number; copies: number; share: number;
}
export interface AccuracyStat {
  confirmed_from_photos: number; kept_as_suggested: number; edited: number;
  keep_rate: number | null; mean_confidence: number | null;
}
export interface CostMonth {
  month: string; model: string | null; calls: number; total_usd: Money; items_found: number;
}
export interface CostSummary {
  total_usd: Money; calls: number; failures: number; items_found: number;
  confirmed_items: number; usd_per_photo: Money; usd_per_confirmed_item: Money | null;
  mean_latency_ms: number | null; by_month: CostMonth[];
}

export interface SystemInfo {
  version: string;
  build: { commit: string | null; built_at: string | null; image: string | null };
  schema: { expected: string | null; applied: string | null; up_to_date: boolean };
  identifier: string; model: string | null; worker_enabled: boolean;
  max_image_edge: number; max_items_per_photo: number;
  photos: { total: number; pending: number; needs_review: number; failed: number };
  items: { total: number; drafts: number; confirmed: number };
}

const query = (params: Record<string, string | number | undefined | null>) =>
  new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value != null && value !== "")
      .map(([key, value]) => [key, String(value)]),
  ).toString();

export const api = {
  me: () => request<SessionInfo>("/api/auth/me"),
  login: (password: string) => request<SessionInfo>("/api/auth/login", json("POST", { password })),
  logout: () => request<SessionInfo>("/api/auth/logout", { method: "POST" }),

  upload(
    files: File[],
    placeId: string | null,
    mode: "scene" | "single",
    onProgress?: (fraction: number) => void,
  ): Promise<UploadResponse> {
    // XHR rather than fetch: upload progress matters on a phone pushing a handful of
    // photos over a VPN, and fetch still cannot report it.
    return new Promise((resolve, reject) => {
      const form = new FormData();
      for (const file of files) form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/photos?${query({ place_id: placeId, mode, source: "web" })}`);
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

  photos: (params: Record<string, string | number | undefined> = {}) =>
    request<Photo[]>(`/api/photos?${query(params)}`),
  photo: (id: string) => request<PhotoDetail>(`/api/photos/${id}`),
  photoImageUrl: (id: string) => `/api/photos/${id}/image`,
  reprocessPhoto: (id: string) =>
    request<PhotoDetail>(`/api/photos/${id}/reprocess`, { method: "POST" }),
  markReviewed: (id: string) =>
    request<PhotoDetail>(`/api/photos/${id}/reviewed`, { method: "POST" }),
  deletePhoto: (id: string) => request<void>(`/api/photos/${id}`, { method: "DELETE" }),

  items: (params: Record<string, string | number | undefined> = {}) =>
    request<Item[]>(`/api/items?${query(params)}`),
  item: (id: string) => request<Item>(`/api/items/${id}`),
  createItem: (body: Record<string, unknown>) => request<Item>("/api/items", json("POST", body)),
  patchItem: (id: string, patch: Record<string, unknown>) =>
    request<Item>(`/api/items/${id}`, json("PATCH", patch)),
  confirmItem: (id: string) => request<Item>(`/api/items/${id}/confirm`, { method: "POST" }),
  rejectItem: (id: string) => request<Item>(`/api/items/${id}/reject`, { method: "POST" }),
  confirmPhotoItems: (photoId: string) =>
    request<Item[]>(`/api/items/confirm-photo/${photoId}`, { method: "POST" }),
  deleteItem: (id: string) => request<void>(`/api/items/${id}`, { method: "DELETE" }),

  itemImageUrl: (id: string) => `/api/items/${id}/image`,
  itemImages: (id: string) => request<ItemImage[]>(`/api/items/${id}/images`),
  addItemImage(id: string, file: File, onProgress?: (fraction: number) => void):
    Promise<ItemImage> {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/items/${id}/images`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
        else {
          let detail = `Feltöltés sikertelen (${xhr.status})`;
          try { detail = JSON.parse(xhr.responseText).detail ?? detail; } catch { /* ignore */ }
          reject(new ApiError(detail, xhr.status));
        }
      };
      xhr.onerror = () => reject(new ApiError("Nem sikerült elérni a szervert.", 0));
      xhr.send(form);
    });
  },
  setPrimaryImage: (imageId: string) =>
    request<ItemImage>(`/api/items/images/${imageId}/primary`, { method: "POST" }),
  deleteItemImage: (imageId: string) =>
    request<void>(`/api/items/images/${imageId}`, { method: "DELETE" }),
  exportCsvUrl: () => "/api/items/export.csv",

  places: () => request<Place[]>("/api/places"),
  createPlace: (body: Record<string, unknown>) => request<Place>("/api/places", json("POST", body)),
  patchPlace: (id: string, patch: Record<string, unknown>) =>
    request<Place>(`/api/places/${id}`, json("PATCH", patch)),
  deletePlace: (id: string) => request<void>(`/api/places/${id}`, { method: "DELETE" }),

  categories: () => request<Category[]>("/api/categories"),

  summary: () => request<StatsSummary>("/api/stats/summary"),
  byPlace: () => request<PlaceStat[]>("/api/stats/by-place"),
  byCategory: () => request<CategoryStat[]>("/api/stats/by-category"),
  accuracy: () => request<AccuracyStat>("/api/stats/accuracy"),
  costs: () => request<CostSummary>("/api/stats/costs"),

  system: () => request<SystemInfo>("/api/system"),
};

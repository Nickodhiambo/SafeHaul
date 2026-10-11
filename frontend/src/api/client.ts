import type {
  AnalyzeRequest,
  AnalyzeResponse,
  HeatmapRequest,
  HeatmapResponse,
  Place,
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 90_000; // free hosting can take a while to wake up

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status = 0,
    public fields?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Worth offering a "try again" button for. */
  get retryable(): boolean {
    return this.code === "network" || this.code === "timeout" || this.code === "upstream_unavailable";
  }
}

export function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(`${BASE_URL}${path}`, { ...init, signal: controller.signal });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON response; handled below */
    }
    if (!res.ok) {
      const err = (body as { error?: { code?: string; message?: string; fields?: Record<string, unknown> } })
        ?.error;
      throw new ApiError(
        err?.code ?? "http_error",
        err?.message ?? `The server returned an error (HTTP ${res.status}).`,
        res.status,
        err?.fields,
      );
    }
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (isAbort(e)) {
      if (timedOut) throw new ApiError("timeout", "The server took too long to respond. Please try again.");
      throw e; // cancelled by the caller: let them handle it
    }
    throw new ApiError("network", "Can't reach the server. Check your connection and try again.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

const jsonPost = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export async function geocode(query: string, signal?: AbortSignal): Promise<Place[]> {
  const data = await request<{ results: Place[] }>(`/api/geocode/?q=${encodeURIComponent(query)}`, {}, signal);
  return data.results;
}

export const analyzeTrip = (payload: AnalyzeRequest, signal?: AbortSignal) =>
  request<AnalyzeResponse>("/api/analyze/", jsonPost(payload), signal);

export const fetchHeatmap = (payload: HeatmapRequest, signal?: AbortSignal) =>
  request<HeatmapResponse>("/api/heatmap/", jsonPost(payload), signal);

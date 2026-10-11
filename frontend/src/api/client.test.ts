import { afterEach, describe, expect, it, vi } from "vitest";
import { analyzeTrip, ApiError, fetchHeatmap, geocode } from "./client";

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("geocode encodes the query and returns results", async () => {
    const fetchMock = vi.fn((_url: string) => json({ results: [{ id: "1", label: "Chicago" }] }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await geocode("St. Louis, MO");
    expect(out).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/geocode/?q=St.%20Louis%2C%20MO");
  });

  it("analyzeTrip POSTs JSON", async () => {
    const fetchMock = vi.fn((_url: string, _init: RequestInit) => json({ routes: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const payload = { origin: { query: "a" }, destination: { query: "b" }, departure: "x", load_lb: 1 };
    await analyzeTrip(payload);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/analyze/");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual(payload);
  });

  it("maps the backend error shape to ApiError", async () => {
    vi.stubGlobal("fetch", () => json({ error: { code: "no_route", message: "No drivable route found" } }, 404));
    await expect(fetchHeatmap({ points: [], start: "", load_lb: 0 })).rejects.toMatchObject({
      code: "no_route", message: "No drivable route found", status: 404,
    });
  });

  it("keeps field errors for invalid requests", async () => {
    vi.stubGlobal("fetch", () =>
      json({ error: { code: "invalid_request", message: "Please check", fields: { load_lb: ["bad"] } } }, 400));
    const err = await analyzeTrip({} as never).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.fields).toEqual({ load_lb: ["bad"] });
  });

  it("handles non-JSON error responses", async () => {
    vi.stubGlobal("fetch", () => Promise.resolve(new Response("<html>Bad gateway</html>", { status: 502 })));
    await expect(geocode("abc")).rejects.toMatchObject({ code: "http_error", status: 502 });
  });

  it("reports network failures as retryable", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
    const err = await geocode("abc").catch((e) => e);
    expect(err.code).toBe("network");
    expect(err.retryable).toBe(true);
  });

  it("marks upstream_unavailable retryable but not no_route", () => {
    expect(new ApiError("upstream_unavailable", "x").retryable).toBe(true);
    expect(new ApiError("no_route", "x").retryable).toBe(false);
  });

  it("lets caller cancellation through as an AbortError", async () => {
    vi.stubGlobal("fetch", (_u: string, init: RequestInit) =>
      new Promise((_res, rej) => init.signal!.addEventListener("abort", () => rej(new DOMException("x", "AbortError")))));
    const ctrl = new AbortController();
    const p = geocode("abc", ctrl.signal);
    ctrl.abort();
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });
});

import { describe, expect, it } from "vitest";
import type { RouteStats } from "../api/types";
import { formatDuration, formatLoad, formatMiles, formatMilesPrecise, formatRate, riskSegments } from "./format";

const stats = (miles: Record<string, number>): RouteStats => ({
  route_id: "r", total_distance_mi: 0, duration_s: 0, miles_by_level: miles, no_travel_miles: 0,
  severe_miles: 0, high_miles: 0, average_risk: 1, max_level: "Low", blocked: false,
});

describe("formatDuration", () => {
  it.each([
    [0, "0 min"], [59, "1 min"], [3600, "1 h"], [3660, "1 h 1 min"], [48_000, "13 h 20 min"], [-5, "0 min"],
  ])("%s s -> %s", (s, expected) => expect(formatDuration(s)).toBe(expected));
});

describe("number formatting", () => {
  it("miles and load use thousands separators", () => {
    expect(formatMiles(802.4)).toBe("802 mi");
    expect(formatMiles(1234.6)).toBe("1,235 mi");
    expect(formatLoad(42000)).toBe("42,000 lb");
  });
  it("precise miles keeps a decimal for small distances", () => {
    expect(formatMilesPrecise(0.44)).toBe("0.4 mi");
    expect(formatMilesPrecise(12.3)).toBe("12 mi");
  });
  it("rates", () => {
    expect(formatRate(0)).toBe("0");
    expect(formatRate(0.004)).toBe("<0.01");
    expect(formatRate(0.15)).toBe("0.15");
  });
});

describe("riskSegments", () => {
  it("returns percentages that add up to 100 and drops empty levels", () => {
    const segs = riskSegments(stats({ Low: 60, Moderate: 0, High: 30, Severe: 10, "No Travel": 0 }));
    expect(segs.map((s) => s.label)).toEqual(["Low", "High", "Severe"]);
    expect(segs.map((s) => s.percent)).toEqual([60, 30, 10]);
    expect(segs.reduce((a, s) => a + s.percent, 0)).toBeCloseTo(100);
  });
  it("is empty when there are no miles", () => {
    expect(riskSegments(stats({}))).toEqual([]);
  });
});

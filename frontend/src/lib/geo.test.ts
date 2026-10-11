import { describe, expect, it } from "vitest";
import type { HeatmapResponse, RouteResult } from "../api/types";
import { checkpointFeatures, heatFeatures, routeBounds, routeFeatures } from "./geo";

const route = (id: string, rank: number, geometry: [number, number][]): RouteResult => ({
  id, rank, recommended: rank === 1, summary: id, distance_mi: 1, duration_s: 1, arrival: "", geometry,
  stats: {} as RouteResult["stats"],
  checkpoints: [
    { index: 0, distance_mi: 0, lat: 1, lon: 2, elapsed_s: 0, eta: "", weather: {} as never,
      risk: { score: 3 } as never },
  ],
});

const heat: HeatmapResponse = {
  start: "", hours: 2, step_hours: 1, load_lb: 0, wind_metric: "sustained", legend: {},
  points: [
    { lat: 1, lon: 2, level: [1, 3, 5], wind_mph: [], rain_in_hr: [], snow_in_hr: [] },
    { lat: 3, lon: 4, level: [2, 2, 2], wind_mph: [], rain_in_hr: [], snow_in_hr: [] },
  ],
};

describe("routeFeatures", () => {
  it("flags the selected route and keeps lon/lat order", () => {
    const fc = routeFeatures([route("a", 1, [[1, 2], [3, 4]]), route("b", 2, [[5, 6], [7, 8]])], "b");
    expect(fc.features.map((f) => f.properties.selected)).toEqual([false, true]);
    expect(fc.features[0].geometry).toEqual({ type: "LineString", coordinates: [[1, 2], [3, 4]] });
    expect(fc.features[0].properties.recommended).toBe(true);
  });
});

describe("checkpointFeatures", () => {
  it("uses [lon, lat] and the risk score as level", () => {
    const fc = checkpointFeatures(route("a", 1, []));
    expect(fc.features[0].geometry).toEqual({ type: "Point", coordinates: [2, 1] });
    expect(fc.features[0].properties).toEqual({ routeId: "a", index: 0, level: 3 });
  });
  it("is empty without a route", () => {
    expect(checkpointFeatures(undefined).features).toEqual([]);
  });
});

describe("heatFeatures", () => {
  it("picks each point's level at the requested hour", () => {
    expect(heatFeatures(heat, 0).features.map((f) => f.properties.level)).toEqual([1, 2]);
    expect(heatFeatures(heat, 2).features.map((f) => f.properties.level)).toEqual([5, 2]);
  });
  it("clamps the hour and tolerates missing data", () => {
    expect(heatFeatures(heat, 99).features[0].properties.level).toBe(5);
    expect(heatFeatures(heat, -3).features[0].properties.level).toBe(1);
    expect(heatFeatures(undefined, 0).features).toEqual([]);
  });
  it("keeps the point index for popups", () => {
    expect(heatFeatures(heat, 1).features.map((f) => f.properties.i)).toEqual([0, 1]);
  });
});

describe("routeBounds", () => {
  it("covers all routes", () => {
    const b = routeBounds([route("a", 1, [[1, 2], [3, 4]]), route("b", 2, [[-5, 0], [2, 9]])]);
    expect(b).toEqual([[-5, 0], [3, 9]]);
  });
  it("is null with no routes", () => {
    expect(routeBounds([])).toBeNull();
  });
});

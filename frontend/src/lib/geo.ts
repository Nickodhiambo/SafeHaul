import type { Checkpoint, HeatmapResponse, RouteResult } from "../api/types";
import { routeColor } from "./risk";

export interface Feature<P> {
  type: "Feature";
  properties: P;
  geometry: { type: "Point"; coordinates: [number, number] } | { type: "LineString"; coordinates: [number, number][] };
}
export interface FeatureCollection<P> {
  type: "FeatureCollection";
  features: Feature<P>[];
}

export type LngLatBounds = [[number, number], [number, number]]; // [[west, south], [east, north]]

export interface RouteProps {
  id: string;
  rank: number;
  color: string;
  selected: boolean;
  recommended: boolean;
}

export function routeFeatures(routes: RouteResult[], selectedId: string | null): FeatureCollection<RouteProps> {
  return {
    type: "FeatureCollection",
    features: routes.map((r) => ({
      type: "Feature",
      properties: {
        id: r.id,
        rank: r.rank,
        color: routeColor(r.rank),
        selected: r.id === selectedId,
        recommended: r.recommended,
      },
      geometry: { type: "LineString", coordinates: r.geometry },
    })),
  };
}

export interface CheckpointProps {
  routeId: string;
  index: number;
  level: number;
}

export function checkpointFeatures(route: RouteResult | undefined): FeatureCollection<CheckpointProps> {
  return {
    type: "FeatureCollection",
    features: (route?.checkpoints ?? []).map((c: Checkpoint) => ({
      type: "Feature",
      properties: { routeId: route!.id, index: c.index, level: c.risk.score },
      geometry: { type: "Point", coordinates: [c.lon, c.lat] },
    })),
  };
}

export interface HeatProps {
  i: number; // index into heatmap.points, for popups
  level: number;
}

/** One frame of the heatmap: every corridor point's risk level at `hour`. */
export function heatFeatures(heat: HeatmapResponse | undefined, hour: number): FeatureCollection<HeatProps> {
  const h = heat ? Math.min(Math.max(hour, 0), heat.hours) : 0;
  return {
    type: "FeatureCollection",
    features: (heat?.points ?? []).map((p, i) => ({
      type: "Feature",
      properties: { i, level: p.level[h] ?? 1 },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  };
}

/** Bounding box of every route, or null if there are none. */
export function routeBounds(routes: RouteResult[]): LngLatBounds | null {
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  for (const r of routes) {
    for (const [lon, lat] of r.geometry) {
      if (lon < west) west = lon;
      if (lon > east) east = lon;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
  }
  return Number.isFinite(west) ? [[west, south], [east, north]] : null;
}

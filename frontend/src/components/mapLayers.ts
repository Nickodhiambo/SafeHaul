import type { Map as MapboxMap } from "mapbox-gl";
import { colorByLevelExpression } from "../lib/risk";

export const SRC = { heat: "heat", routes: "routes", checkpoints: "checkpoints" } as const;
export const LAYER = {
  heatmap: "heat-heatmap",
  heatPoints: "heat-points",
  routeHit: "route-hit",
  routeCasing: "route-casing",
  routeLine: "route-line",
  checkpoints: "checkpoints-circle",
} as const;

const EMPTY = { type: "FeatureCollection", features: [] } as const;

/** Mapbox expression typing is stricter than it's worth here; the specs below are validated at runtime. */
const x = (e: unknown) => e as never;

const SELECTED = ["get", "selected"];

/**
 * Sources and layers, bottom to top: heatmap, heat points, route hit-area, route casing,
 * route line, checkpoint dots. Data is swapped in with `source.setData`, so the layers are
 * created once and never rebuilt (that is what keeps the slider smooth).
 */
export function addMapLayers(map: MapboxMap): void {
  map.addSource(SRC.heat, { type: "geojson", data: EMPTY as never });
  map.addSource(SRC.routes, { type: "geojson", data: EMPTY as never });
  map.addSource(SRC.checkpoints, { type: "geojson", data: EMPTY as never });

  map.addLayer({
    id: LAYER.heatmap,
    type: "heatmap",
    source: SRC.heat,
    paint: {
      // Low risk contributes nothing, so calm stretches stay clear and only trouble glows.
      "heatmap-weight": x(["match", ["get", "level"], 1, 0, 2, 0.3, 3, 0.55, 4, 0.85, 5, 1, 0]),
      "heatmap-intensity": x(["interpolate", ["linear"], ["zoom"], 3, 1, 9, 1.6]),
      "heatmap-radius": x(["interpolate", ["exponential", 2], ["zoom"], 3, 6, 5, 16, 7, 48, 9, 150, 11, 380]),
      "heatmap-color": x([
        "interpolate", ["linear"], ["heatmap-density"],
        0, "rgba(255,255,255,0)",
        0.1, "rgba(250,204,21,0.40)",
        0.35, "rgba(251,146,60,0.62)",
        0.65, "rgba(220,38,38,0.78)",
        1, "rgba(88,28,135,0.88)",
      ]),
      "heatmap-opacity": x(["interpolate", ["linear"], ["zoom"], 9, 0.9, 12, 0.5]),
    },
  });

  map.addLayer({
    id: LAYER.heatPoints,
    type: "circle",
    source: SRC.heat,
    minzoom: 6.5,
    paint: {
      "circle-radius": x(["interpolate", ["linear"], ["zoom"], 6.5, 2.5, 11, 7]),
      "circle-color": x(colorByLevelExpression("level")),
      "circle-opacity": x(["match", ["get", "level"], 1, 0.35, 0.9]),
      "circle-stroke-width": 1,
      "circle-stroke-color": "#ffffff",
    },
  });

  // Wide invisible line so routes are easy to tap on a phone
  map.addLayer({
    id: LAYER.routeHit,
    type: "line",
    source: SRC.routes,
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-width": 22, "line-opacity": 0 },
  });
  map.addLayer({
    id: LAYER.routeCasing,
    type: "line",
    source: SRC.routes,
    layout: { "line-cap": "round", "line-join": "round", "line-sort-key": x(["case", SELECTED, 1, 0]) },
    paint: { "line-color": "#ffffff", "line-width": x(["case", SELECTED, 10, 7]), "line-opacity": 0.9 },
  });
  map.addLayer({
    id: LAYER.routeLine,
    type: "line",
    source: SRC.routes,
    layout: { "line-cap": "round", "line-join": "round", "line-sort-key": x(["case", SELECTED, 1, 0]) },
    paint: {
      "line-color": x(["get", "color"]),
      "line-width": x(["case", SELECTED, 6, 4]),
      "line-opacity": x(["case", SELECTED, 1, 0.6]),
    },
  });

  map.addLayer({
    id: LAYER.checkpoints,
    type: "circle",
    source: SRC.checkpoints,
    paint: {
      "circle-radius": x(["interpolate", ["linear"], ["zoom"], 4, 4, 10, 8]),
      "circle-color": x(colorByLevelExpression("level")),
      "circle-stroke-width": 2,
      "circle-stroke-color": "#ffffff",
    },
  });
}

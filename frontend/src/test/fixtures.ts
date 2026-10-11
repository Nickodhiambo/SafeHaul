import type { AnalyzeResponse, Checkpoint, HeatmapResponse, RouteResult } from "../api/types";

const cp = (index: number, mile: number, score: 1 | 2 | 3 | 4 | 5, reason: string): Checkpoint => ({
  index, distance_mi: mile, lat: 40 + index * 0.1, lon: -80 - index * 0.2, elapsed_s: index * 3600,
  eta: `2026-10-13T0${5 + index}:00:00+00:00`,
  weather: { time: "", wind_mph: 12 + index * 10, gust_mph: 20, rain_in_hr: score >= 3 ? 0.3 : 0, snow_in_hr: 0 },
  risk: {
    level: ["Low", "Moderate", "High", "Severe", "No Travel"][score - 1], score, wind_level: "Low",
    rain_level: "Low", snow_level: "Low", load_adjusted: score === 5, driver: "wind", reason,
  },
});

export const route = (id: string, rank: number, recommended: boolean, blocked = false): RouteResult => ({
  id, rank, recommended, summary: rank === 1 ? "I-80, I-90" : "US-30", distance_mi: 802.4, duration_s: 48_000,
  arrival: "2026-10-13T18:20:00+00:00",
  stats: {
    route_id: id, total_distance_mi: 802.4, duration_s: 48_000,
    miles_by_level: { Low: 700, Moderate: 50, High: 40, Severe: 12.4, "No Travel": blocked ? 20 : 0 },
    no_travel_miles: blocked ? 20 : 0, severe_miles: 12.4, high_miles: 40, average_risk: 1.3,
    max_level: blocked ? "No Travel" : "Severe", blocked,
  },
  geometry: [[-74, 40.7], [-80, 41], [-87.6, 41.9]],
  checkpoints: [cp(0, 0, 1, "Conditions within safe limits"), cp(1, 25, 3, "Rain 0.3 in/hr → High"), cp(2, 50, 5, "Wind 47 mph with a 35,000 lb load → No Travel")],
});

export const analysis = (blocked = false): AnalyzeResponse => ({
  request: {
    origin: { lat: 40.7, lon: -74, label: "New York, NY" },
    destination: { lat: 41.9, lon: -87.6, label: "Chicago, IL" },
    departure: "2026-10-13T05:00:00+00:00", load_lb: 42000,
  },
  recommended_route_id: "route-1",
  recommendation: { summary: "Recommended for fewest Severe miles: 0.0 mi vs 12.4 mi on the next best route." },
  routes: [route("route-1", 1, true, blocked), route("route-2", 2, false, blocked)],
  corridor: [{ lat: 40.7, lon: -74 }],
  meta: { wind_metric: "sustained", generated_at: "2026-10-12T10:00:00+00:00" },
});

export const heatmap: HeatmapResponse = {
  start: "2026-10-13T05:00:00+00:00", hours: 3, step_hours: 1, load_lb: 42000, wind_metric: "sustained",
  legend: {}, points: [{ lat: 40.7, lon: -74, level: [1, 2, 4, 3], wind_mph: [5, 20, 46, 36], rain_in_hr: [0, 0, 0, 0], snow_in_hr: [0, 0, 0, 0] }],
};

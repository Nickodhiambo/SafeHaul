/** Shapes returned by the SafeHaul Django API. */

export type RiskScore = 1 | 2 | 3 | 4 | 5;

export interface LatLon {
  lat: number;
  lon: number;
}

export interface Place {
  id: string;
  name: string;
  label: string;
  lat: number;
  lon: number;
  type: string;
}

/** A trip endpoint as sent to the API: exact coordinates or free text to geocode. */
export interface PlaceInput {
  lat?: number;
  lon?: number;
  label?: string;
  query?: string;
}

export interface Weather {
  time: string;
  wind_mph: number;
  gust_mph: number;
  rain_in_hr: number;
  snow_in_hr: number;
}

export interface Risk {
  level: string;
  score: RiskScore;
  wind_level: string;
  rain_level: string;
  snow_level: string;
  load_adjusted: boolean;
  driver: string;
  reason: string;
}

export interface Checkpoint {
  index: number;
  distance_mi: number;
  lat: number;
  lon: number;
  elapsed_s: number;
  eta: string;
  weather: Weather;
  risk: Risk;
}

export interface RouteStats {
  route_id: string;
  total_distance_mi: number;
  duration_s: number;
  miles_by_level: Record<string, number>; // keyed by level label: "Low" ... "No Travel"
  no_travel_miles: number;
  severe_miles: number;
  high_miles: number;
  average_risk: number;
  max_level: string;
  blocked: boolean;
}

export interface RouteResult {
  id: string;
  summary: string;
  rank: number;
  recommended: boolean;
  distance_mi: number;
  duration_s: number;
  arrival: string;
  stats: RouteStats;
  geometry: [number, number][]; // [lon, lat]
  checkpoints: Checkpoint[];
}

export interface AnalyzeRequest {
  origin: PlaceInput;
  destination: PlaceInput;
  departure: string; // ISO 8601 with offset
  load_lb: number;
}

export interface AnalyzeResponse {
  request: {
    origin: { lat: number; lon: number; label: string };
    destination: { lat: number; lon: number; label: string };
    departure: string;
    load_lb: number;
  };
  recommended_route_id: string;
  recommendation: { summary: string };
  routes: RouteResult[]; // best first
  corridor: LatLon[];
  meta: { wind_metric: string; generated_at: string };
}

export interface HeatmapPoint {
  lat: number;
  lon: number;
  level: number[];
  wind_mph: number[];
  rain_in_hr: number[];
  snow_in_hr: number[];
}

export interface HeatmapRequest {
  points: LatLon[];
  start: string;
  load_lb: number;
  hours?: number;
}

export interface HeatmapResponse {
  start: string;
  hours: number; // slider runs 0..hours
  step_hours: number;
  load_lb: number;
  wind_metric: string;
  legend: Record<string, string>;
  points: HeatmapPoint[];
}

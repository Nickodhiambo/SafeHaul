import type { AnalyzeRequest, Place, PlaceInput } from "../api/types";
import { departureProblem, toIsoUtc } from "./time";

export const MAX_LOAD_LB = 150_000; // keep in sync with the backend

export interface TripFormState {
  originText: string;
  originPlace: Place | null;
  destText: string;
  destPlace: Place | null;
  departureLocal: string;
  loadText: string;
}

export interface TripErrors {
  origin?: string;
  destination?: string;
  departure?: string;
  load?: string;
}

/** Parse "42,000" / "42000" / " 42 000 " into a number, or null. */
export function parseLoad(text: string): number | null {
  const cleaned = text.replace(/[,\s]/g, "");
  if (cleaned === "" || !/^\d+(\.\d+)?$/.test(cleaned)) return null;
  return Number(cleaned);
}

const toPlaceInput = (text: string, place: Place | null): PlaceInput | null => {
  if (place) return { lat: place.lat, lon: place.lon, label: place.label };
  const q = text.trim();
  return q ? { query: q } : null;
};

const sameSpot = (a: Place, b: Place) =>
  Math.abs(a.lat - b.lat) < 0.001 && Math.abs(a.lon - b.lon) < 0.001;

export function validateTrip(
  s: TripFormState,
  now: Date = new Date(),
): { request?: AnalyzeRequest; errors: TripErrors } {
  const errors: TripErrors = {};

  const origin = toPlaceInput(s.originText, s.originPlace);
  const destination = toPlaceInput(s.destText, s.destPlace);
  if (!origin) errors.origin = "Enter where the trip starts.";
  if (!destination) errors.destination = "Enter where the trip ends.";
  if (s.originPlace && s.destPlace && sameSpot(s.originPlace, s.destPlace))
    errors.destination = "Destination is the same place as the start.";

  const problem = departureProblem(s.departureLocal, now);
  if (problem) errors.departure = problem;

  const load = parseLoad(s.loadText);
  if (load === null) errors.load = "Enter the load weight in pounds.";
  else if (load > MAX_LOAD_LB) errors.load = `Load can't exceed ${MAX_LOAD_LB.toLocaleString("en-US")} lb.`;

  if (Object.keys(errors).length > 0) return { errors };
  return {
    errors,
    request: {
      origin: origin!,
      destination: destination!,
      departure: toIsoUtc(s.departureLocal)!,
      load_lb: load!,
    },
  };
}

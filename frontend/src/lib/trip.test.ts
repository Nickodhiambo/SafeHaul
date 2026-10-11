import { beforeAll, describe, expect, it } from "vitest";
import type { Place } from "../api/types";
import { parseLoad, validateTrip, type TripFormState } from "./trip";

beforeAll(() => {
  process.env.TZ = "Africa/Nairobi";
});

const place = (label: string, lat: number, lon: number): Place => ({ id: label, name: label, label, lat, lon, type: "place" });
const NOW = new Date("2026-10-12T05:00:00Z");
const valid: TripFormState = {
  originText: "New York, NY", originPlace: place("New York, NY", 40.71, -74.0),
  destText: "Chicago, IL", destPlace: place("Chicago, IL", 41.88, -87.63),
  departureLocal: "2026-10-13T08:00", loadText: "42,000",
};

describe("parseLoad", () => {
  it.each([["42000", 42000], ["42,000", 42000], [" 42 000 ", 42000], ["0", 0], ["12.5", 12.5]])("%s", (t, n) =>
    expect(parseLoad(t as string)).toBe(n));
  it.each(["", "abc", "-5", "1e5", "12,5,6x"])("rejects %j", (t) => expect(parseLoad(t)).toBeNull());
});

describe("validateTrip", () => {
  it("builds the API request from picked places", () => {
    const { request, errors } = validateTrip(valid, NOW);
    expect(errors).toEqual({});
    expect(request).toEqual({
      origin: { lat: 40.71, lon: -74.0, label: "New York, NY" },
      destination: { lat: 41.88, lon: -87.63, label: "Chicago, IL" },
      departure: "2026-10-13T05:00:00.000Z",
      load_lb: 42000,
    });
  });

  it("falls back to a text query when no suggestion was picked", () => {
    const { request } = validateTrip({ ...valid, originPlace: null, originText: "  Dallas, TX " }, NOW);
    expect(request?.origin).toEqual({ query: "Dallas, TX" });
  });

  it("reports every problem at once", () => {
    const { request, errors } = validateTrip(
      { ...valid, originText: " ", originPlace: null, destText: "", destPlace: null, departureLocal: "", loadText: "" }, NOW);
    expect(request).toBeUndefined();
    expect(Object.keys(errors).sort()).toEqual(["departure", "destination", "load", "origin"]);
  });

  it("rejects identical start and end", () => {
    const { errors } = validateTrip({ ...valid, destPlace: valid.originPlace }, NOW);
    expect(errors.destination).toMatch(/same place/);
  });

  it("rejects an overweight load and a past departure", () => {
    expect(validateTrip({ ...valid, loadText: "200000" }, NOW).errors.load).toMatch(/exceed/);
    expect(validateTrip({ ...valid, departureLocal: "2026-10-01T08:00" }, NOW).errors.departure).toMatch(/past/);
  });

  it("allows zero load (empty trailer)", () => {
    expect(validateTrip({ ...valid, loadText: "0" }, NOW).request?.load_lb).toBe(0);
  });
});

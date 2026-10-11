import { beforeAll, describe, expect, it } from "vitest";
import { addHours, defaultDeparture, departureProblem, toIsoUtc, toLocalInputValue } from "./time";

beforeAll(() => {
  process.env.TZ = "Africa/Nairobi"; // UTC+3, no DST: makes local-time tests deterministic
});

describe("toIsoUtc", () => {
  it("converts Nairobi 8:00 am to 05:00 UTC", () => {
    expect(toIsoUtc("2026-10-12T08:00")).toBe("2026-10-12T05:00:00.000Z");
  });
  it("rejects empty and invalid values", () => {
    expect(toIsoUtc("")).toBeNull();
    expect(toIsoUtc("not a date")).toBeNull();
  });
});

describe("defaultDeparture", () => {
  it("is the start of the next full hour", () => {
    expect(defaultDeparture(new Date("2026-10-12T05:20:00Z"))).toBe("2026-10-12T09:00"); // 08:20 local -> 09:00
  });
  it("rolls over midnight", () => {
    expect(defaultDeparture(new Date("2026-10-12T20:59:00Z"))).toBe("2026-10-13T00:00"); // 23:59 local
  });
});

describe("toLocalInputValue", () => {
  it("pads fields", () => {
    expect(toLocalInputValue(new Date(2026, 0, 5, 7, 4))).toBe("2026-01-05T07:04");
  });
});

describe("departureProblem", () => {
  const now = new Date("2026-10-12T05:00:00Z");
  it("accepts a normal future time", () => {
    expect(departureProblem("2026-10-13T08:00", now)).toBeNull();
  });
  it("accepts a few minutes ago (backend allows a 1 h grace)", () => {
    expect(departureProblem("2026-10-12T07:30", now)).toBeNull();
  });
  it("rejects the past, the far future and empty", () => {
    expect(departureProblem("2026-10-11T08:00", now)).toMatch(/past/);
    expect(departureProblem("2026-12-01T08:00", now)).toMatch(/16 days/);
    expect(departureProblem("", now)).toMatch(/Choose/);
  });
});

describe("addHours", () => {
  it("adds across a day boundary", () => {
    expect(addHours("2026-10-12T22:00:00.000Z", 5)).toBe("2026-10-13T03:00:00.000Z");
  });
});

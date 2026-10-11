import { describe, expect, it } from "vitest";
import { colorByLevelExpression, levelColor, levelLabel, RISK_LEVELS, routeColor } from "./risk";

describe("risk scale", () => {
  it("matches the backend's five levels in order", () => {
    expect(RISK_LEVELS.map((l) => l.label)).toEqual(["Low", "Moderate", "High", "Severe", "No Travel"]);
    expect(RISK_LEVELS.map((l) => l.score)).toEqual([1, 2, 3, 4, 5]);
  });
  it("clamps out-of-range scores", () => {
    expect(levelLabel(0)).toBe("Low");
    expect(levelLabel(9)).toBe("No Travel");
    expect(levelColor(4)).toBe(RISK_LEVELS[3].color);
  });
  it("has distinct colours", () => {
    expect(new Set(RISK_LEVELS.map((l) => l.color)).size).toBe(5);
  });
});

describe("colorByLevelExpression", () => {
  it("builds a Mapbox match expression with a fallback", () => {
    const e = colorByLevelExpression();
    expect(e[0]).toBe("match");
    expect(e[1]).toEqual(["get", "level"]);
    expect(e.length).toBe(2 + 5 * 2 + 1);
  });
});

describe("routeColor", () => {
  it("is stable by rank and wraps", () => {
    expect(routeColor(1)).toBe(routeColor(4));
    expect(routeColor(1)).not.toBe(routeColor(2));
  });
});

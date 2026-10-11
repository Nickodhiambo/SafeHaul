import type { RiskScore } from "../api/types";

export interface RiskLevelInfo {
  score: RiskScore;
  label: string;
  color: string;
  /** Text colour that stays readable on `color`. */
  ink: string;
}

/** Same scale as the backend: 1 Low ... 5 No Travel. */
export const RISK_LEVELS: readonly RiskLevelInfo[] = [
  { score: 1, label: "Low", color: "#22a55b", ink: "#ffffff" },
  { score: 2, label: "Moderate", color: "#eab308", ink: "#1f2937" },
  { score: 3, label: "High", color: "#f97316", ink: "#1f2937" },
  { score: 4, label: "Severe", color: "#dc2626", ink: "#ffffff" },
  { score: 5, label: "No Travel", color: "#581c87", ink: "#ffffff" },
];

export function levelInfo(score: number): RiskLevelInfo {
  const clamped = Math.min(5, Math.max(1, Math.round(score)));
  return RISK_LEVELS[clamped - 1];
}

export const levelColor = (score: number) => levelInfo(score).color;
export const levelLabel = (score: number) => levelInfo(score).label;

/** Mapbox `match` expression colouring a feature by its numeric `level` property. */
export function colorByLevelExpression(prop = "level"): unknown[] {
  const expr: unknown[] = ["match", ["get", prop]];
  for (const l of RISK_LEVELS) expr.push(l.score, l.color);
  expr.push("#9ca3af");
  return expr;
}

export const ROUTE_COLORS = ["#2563eb", "#7c3aed", "#0891b2"] as const;
export const routeColor = (rank: number) => ROUTE_COLORS[(Math.max(rank, 1) - 1) % ROUTE_COLORS.length];

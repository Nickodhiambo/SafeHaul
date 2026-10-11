import type { RouteStats } from "../api/types";
import { RISK_LEVELS } from "./risk";

export function formatDuration(seconds: number): string {
  const totalMin = Math.max(0, Math.round(seconds / 60));
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export const formatMiles = (mi: number) => `${Math.round(mi).toLocaleString("en-US")} mi`;

/** Miles with one decimal below 10 mi, so "0.4 mi" doesn't read as "0 mi". */
export const formatMilesPrecise = (mi: number) =>
  mi < 10 ? `${(Math.round(mi * 10) / 10).toFixed(1)} mi` : formatMiles(mi);

export const formatLoad = (lb: number) => `${Math.round(lb).toLocaleString("en-US")} lb`;

export interface RiskSegment {
  score: number;
  label: string;
  color: string;
  miles: number;
  /** Share of the route, 0..100. */
  percent: number;
}

/** Stacked-bar data for "how many miles at each risk level". Zero-mile levels are dropped. */
export function riskSegments(stats: RouteStats): RiskSegment[] {
  const total = RISK_LEVELS.reduce((sum, l) => sum + (stats.miles_by_level[l.label] ?? 0), 0);
  if (total <= 0) return [];
  return RISK_LEVELS.map((l) => {
    const miles = stats.miles_by_level[l.label] ?? 0;
    return { score: l.score, label: l.label, color: l.color, miles, percent: (miles / total) * 100 };
  }).filter((s) => s.miles > 0);
}

/** "Rain 0.15 in/hr", but "0" instead of "0.00". */
export const formatRate = (v: number) => (v === 0 ? "0" : v < 0.01 ? "<0.01" : v.toFixed(2));

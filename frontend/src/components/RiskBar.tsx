import type { RouteStats } from "../api/types";
import { riskSegments } from "../lib/format";

/** Stacked bar: what share of the route's miles sit at each risk level. */
export function RiskBar({ stats }: { stats: RouteStats }) {
  const segments = riskSegments(stats);
  const description = segments.map((s) => `${s.label} ${Math.round(s.percent)}%`).join(", ");
  return (
    <div className="riskbar" role="img" aria-label={`Miles by risk level: ${description}`}>
      {segments.map((s) => (
        <span
          key={s.score}
          className="riskbar-seg"
          style={{ width: `${s.percent}%`, background: s.color }}
          title={`${s.label}: ${Math.round(s.miles)} mi`}
        />
      ))}
    </div>
  );
}

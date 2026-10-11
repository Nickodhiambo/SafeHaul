import type { AnalyzeResponse, RouteResult } from "../api/types";
import { formatDayTime } from "../lib/time";
import { formatDuration, formatMiles, formatMilesPrecise } from "../lib/format";
import { levelInfo, routeColor } from "../lib/risk";
import { RiskBar } from "./RiskBar";

interface Props {
  analysis: AnalyzeResponse;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function RouteCards({ analysis, selectedId, onSelect }: Props) {
  const { routes, recommendation } = analysis;
  const allBlocked = routes.every((r) => r.stats.blocked);
  const best = routes.find((r) => r.recommended);

  return (
    <section aria-label="Route options" className="routes">
      <div className={`reco${allBlocked ? " reco-danger" : ""}`} role="status">
        <strong className="reco-title">
          {allBlocked ? "No Travel conditions on every route" : `Recommended: ${best ? routeName(best) : "—"}`}
        </strong>
        <span>{recommendation.summary}</span>
      </div>

      <ul className="route-list">
        {routes.map((r) => (
          <li key={r.id}>
            <RouteCard route={r} selected={r.id === selectedId} onSelect={() => onSelect(r.id)} />
          </li>
        ))}
      </ul>
    </section>
  );
}

export const routeName = (r: RouteResult) => r.summary || `Route ${r.rank}`;

function RouteCard({ route, selected, onSelect }: { route: RouteResult; selected: boolean; onSelect: () => void }) {
  const s = route.stats;
  const worst = levelInfo(["Low", "Moderate", "High", "Severe", "No Travel"].indexOf(s.max_level) + 1);
  return (
    <button
      type="button"
      className={`route-card${selected ? " is-selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
      style={{ ["--route-color" as string]: routeColor(route.rank) }}
    >
      <span className="route-head">
        <span className="route-rank" aria-hidden="true">
          {route.rank}
        </span>
        <span className="route-title">{routeName(route)}</span>
        {route.recommended && <span className="tag tag-good">Recommended</span>}
      </span>

      <span className="route-metrics">
        <span>
          <b>{formatDuration(route.duration_s)}</b>
          <small>drive time</small>
        </span>
        <span>
          <b>{formatMiles(route.distance_mi)}</b>
          <small>distance</small>
        </span>
        <span>
          <b>{formatDayTime(route.arrival)}</b>
          <small>arrival</small>
        </span>
      </span>

      <RiskBar stats={s} />

      <span className="route-risk">
        {s.blocked ? (
          <span className="tag tag-block">No Travel: {formatMilesPrecise(s.no_travel_miles)}</span>
        ) : null}
        <span>
          Severe <b>{formatMilesPrecise(s.severe_miles)}</b>
        </span>
        <span>
          High <b>{formatMilesPrecise(s.high_miles)}</b>
        </span>
        <span>
          Worst{" "}
          <b className="dot-label">
            <i className="dot" style={{ background: worst.color }} />
            {worst.label}
          </b>
        </span>
      </span>
    </button>
  );
}

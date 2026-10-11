import type { Checkpoint, RouteResult } from "../api/types";
import { formatRate } from "../lib/format";
import { levelInfo } from "../lib/risk";
import { formatDayTime } from "../lib/time";
import { routeName } from "./RouteCards";

interface Props {
  route: RouteResult;
  onFocus: (index: number) => void;
}

/** Checkpoint-by-checkpoint breakdown for the selected route. */
export function RouteDetail({ route, onFocus }: Props) {
  return (
    <section aria-label="Checkpoints" className="detail">
      <h2 className="section-title">
        Checkpoints <span className="muted">· {routeName(route)}</span>
      </h2>
      <ol className="cp-list">
        {route.checkpoints.map((c) => (
          <CheckpointRow key={c.index} cp={c} onFocus={() => onFocus(c.index)} />
        ))}
      </ol>
    </section>
  );
}

function CheckpointRow({ cp, onFocus }: { cp: Checkpoint; onFocus: () => void }) {
  const lvl = levelInfo(cp.risk.score);
  const w = cp.weather;
  return (
    <li>
      <button type="button" className="cp-row" onClick={onFocus} aria-label={`Show mile ${Math.round(cp.distance_mi)} on the map`}>
        <span className="cp-when">
          <b>{formatDayTime(cp.eta)}</b>
          <small>mile {Math.round(cp.distance_mi).toLocaleString("en-US")}</small>
        </span>
        <span className="chip-risk" style={{ background: lvl.color, color: lvl.ink }}>
          {lvl.label}
        </span>
        <span className="cp-cond">
          <span>Wind {Math.round(w.wind_mph)} mph</span>
          <span>Rain {formatRate(w.rain_in_hr)} in/hr</span>
          <span>Snow {formatRate(w.snow_in_hr)} in/hr</span>
        </span>
        {cp.risk.score >= 2 && <span className="cp-reason">{cp.risk.reason}</span>}
        {cp.risk.load_adjusted && <span className="cp-reason cp-load">Heavy-load rule applied</span>}
      </button>
    </li>
  );
}


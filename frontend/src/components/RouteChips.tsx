import type { RouteResult } from "../api/types";
import { routeColor } from "../lib/risk";
import { routeName } from "./RouteCards";

interface Props {
  routes: RouteResult[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** Compact route switcher over the map (shown on phones, where the card list is on another tab). */
export function RouteChips({ routes, selectedId, onSelect }: Props) {
  return (
    <div className="route-chips" role="group" aria-label="Choose route">
      {routes.map((r) => (
        <button
          key={r.id}
          type="button"
          className={`route-chip${r.id === selectedId ? " is-selected" : ""}`}
          aria-pressed={r.id === selectedId}
          onClick={() => onSelect(r.id)}
          style={{ ["--route-color" as string]: routeColor(r.rank) }}
        >
          <span className="route-chip-rank">{r.rank}</span>
          {r.recommended ? "★ " : ""}
          {routeName(r)}
        </button>
      ))}
    </div>
  );
}

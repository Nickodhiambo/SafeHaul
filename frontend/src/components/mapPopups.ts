import type { Checkpoint, HeatmapPoint } from "../api/types";
import { formatRate } from "../lib/format";
import { levelInfo } from "../lib/risk";
import { formatDayTime } from "../lib/time";

/** Popups are built with DOM nodes and `textContent`, never HTML strings, so API text can't inject markup. */
function el<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function riskChip(score: number): HTMLElement {
  const lvl = levelInfo(score);
  const chip = el("span", "chip-risk", lvl.label);
  chip.style.background = lvl.color;
  chip.style.color = lvl.ink;
  return chip;
}

function conditions(wind: number, rain: number, snow: number): HTMLElement {
  const list = el("div", "pop-cond");
  list.append(
    el("span", "", `Wind ${Math.round(wind)} mph`),
    el("span", "", `Rain ${formatRate(rain)} in/hr`),
    el("span", "", `Snow ${formatRate(snow)} in/hr`),
  );
  return list;
}

export function checkpointPopup(cp: Checkpoint): HTMLElement {
  const root = el("div", "pop");
  const head = el("div", "pop-head");
  head.append(el("b", "", `Mile ${Math.round(cp.distance_mi).toLocaleString("en-US")}`), riskChip(cp.risk.score));
  root.append(head, el("div", "pop-sub", `Arrive ${formatDayTime(cp.eta)}`), conditions(cp.weather.wind_mph, cp.weather.rain_in_hr, cp.weather.snow_in_hr));
  if (cp.risk.score >= 2) root.append(el("div", "pop-reason", cp.risk.reason));
  return root;
}

export function heatPopup(point: HeatmapPoint, hour: number, timeLabel: string): HTMLElement {
  const root = el("div", "pop");
  const head = el("div", "pop-head");
  head.append(el("b", "", timeLabel), riskChip(point.level[hour] ?? 1));
  root.append(head, conditions(point.wind_mph[hour] ?? 0, point.rain_in_hr[hour] ?? 0, point.snow_in_hr[hour] ?? 0));
  return root;
}

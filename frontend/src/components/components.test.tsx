import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { analysis, heatmap, route } from "../test/fixtures";
import { HeatmapControl } from "./HeatmapControl";
import { PlaceInput } from "./PlaceInput";
import { RiskBar } from "./RiskBar";
import { RouteCards } from "./RouteCards";
import { RouteChips } from "./RouteChips";
import { RouteDetail } from "./RouteDetail";
import { ErrorBanner, LoadingPanel } from "./StatusPanels";
import { TripForm } from "./TripForm";

const html = (el: React.ReactElement) => renderToStaticMarkup(el);
const noop = () => {};

describe("TripForm", () => {
  it("renders every field with accessible labels and the submit button", () => {
    const out = html(<TripForm loading={false} onSubmit={noop} />);
    for (const text of ["Origin", "Destination", "Departure", "Load weight (lb)", "Find the safest route"]) {
      expect(out).toContain(text);
    }
    expect(out).toContain('type="datetime-local"');
    expect(out).toContain('role="combobox"');
  });
  it("disables submit while analyzing", () => {
    const out = html(<TripForm loading onSubmit={noop} />);
    expect(out).toContain("Analyzing");
    expect(out).toMatch(/<button[^>]*disabled[^>]*>/);
  });
});

describe("PlaceInput", () => {
  it("shows an error message and marks the field invalid", () => {
    const out = html(<PlaceInput label="Origin" marker="A" placeholder="x" value="" selected={null} onChange={noop} error="Enter where the trip starts." />);
    expect(out).toContain("Enter where the trip starts.");
    expect(out).toContain('aria-invalid="true"');
  });
});

describe("RouteCards", () => {
  it("shows the recommendation, metrics and risk summary for each route", () => {
    const out = html(<RouteCards analysis={analysis()} selectedId="route-1" onSelect={noop} />);
    expect(out).toContain("Recommended: I-80, I-90");
    expect(out).toContain("fewest Severe miles");
    expect(out).toContain("13 h 20 min");
    expect(out).toContain("802 mi");
    expect(out).toContain('aria-pressed="true"');
    expect(out).toContain('aria-pressed="false"');
    expect(out).toContain("US-30");
  });
  it("warns when every route has No Travel stretches", () => {
    const out = html(<RouteCards analysis={analysis(true)} selectedId="route-1" onSelect={noop} />);
    expect(out).toContain("No Travel conditions on every route");
    expect(out).toContain("No Travel: 20 mi");
  });
});

describe("RiskBar", () => {
  it("describes the split for screen readers", () => {
    const out = html(<RiskBar stats={route("r", 1, true).stats} />);
    expect(out).toContain("Miles by risk level");
    expect(out).toContain("Low 87%");
  });
});

describe("RouteDetail", () => {
  it("lists checkpoints with conditions and explains risky ones", () => {
    const out = html(<RouteDetail route={route("route-1", 1, true)} onFocus={noop} />);
    expect(out).toContain("mile 25");
    expect(out).toContain("Rain 0.30 in/hr");
    expect(out).toContain("Rain 0.3 in/hr → High");
    expect(out).toContain("Heavy-load rule applied");
    expect(out).not.toContain("Conditions within safe limits"); // low-risk rows stay quiet
  });
});

describe("RouteChips", () => {
  it("marks the recommended and selected routes", () => {
    const out = html(<RouteChips routes={analysis().routes} selectedId="route-2" onSelect={noop} />);
    expect(out).toContain("★ I-80, I-90");
    expect(out.match(/aria-pressed="true"/g)).toHaveLength(1);
  });
});

describe("HeatmapControl", () => {
  const base = { hour: 2, onHour: noop, show: true, onToggle: noop, onRetry: noop };
  it("renders the slider for the available hours and the worst level at that hour", () => {
    const out = html(<HeatmapControl {...base} heat={{ status: "ready", data: heatmap }} />);
    expect(out).toContain('max="3"');
    expect(out).toContain('value="2"');
    expect(out).toContain("+2 h");
    expect(out).toContain("Severe"); // level 4 at hour 2
    expect(out).toContain('aria-label="Risk legend"');
  });
  it("shows loading and error states without hiding the routes", () => {
    expect(html(<HeatmapControl {...base} heat={{ status: "loading" }} />)).toContain("Loading the 48-hour forecast");
    const err = html(<HeatmapControl {...base} heat={{ status: "error", error: new ApiError("network", "x") }} />);
    expect(err).toContain("couldn&#x27;t load");
    expect(err).toContain("Retry");
  });
  it("disables the slider when the heatmap is switched off", () => {
    const out = html(<HeatmapControl {...base} show={false} heat={{ status: "ready", data: heatmap }} />);
    expect(out).toMatch(/<input[^>]*type="range"[^>]*disabled/);
  });
});

describe("status panels", () => {
  it("loading panel is announced as busy", () => {
    expect(html(<LoadingPanel />)).toContain('aria-busy="true"');
  });
  it("error banner offers retry only for retryable errors", () => {
    expect(html(<ErrorBanner error={new ApiError("upstream_unavailable", "Try later")} onRetry={noop} />)).toContain("Try again");
    const permanent = html(<ErrorBanner error={new ApiError("no_route", "No drivable route found")} onRetry={noop} />);
    expect(permanent).toContain("No route found");
    expect(permanent).not.toContain("Try again");
  });
});

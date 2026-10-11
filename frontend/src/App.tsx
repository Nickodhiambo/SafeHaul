import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { HeatmapControl } from "./components/HeatmapControl";
import type { MapFocus } from "./components/MapView";
import { RouteCards } from "./components/RouteCards";
import { RouteChips } from "./components/RouteChips";
import { RouteDetail } from "./components/RouteDetail";
import { ErrorBanner, LoadingPanel } from "./components/StatusPanels";
import { TripForm } from "./components/TripForm";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useTrip } from "./hooks/useTrip";
import { RISK_LEVELS } from "./lib/risk";

// The map library is large; load it after the form has painted.
const MapView = lazy(() => import("./components/MapView"));

type Tab = "plan" | "map";

export default function App() {
  const trip = useTrip();
  const { status, analysis, error, selectedId, heat } = trip;
  const isDesktop = useMediaQuery("(min-width: 900px)");

  const [tab, setTab] = useState<Tab>("plan");
  const [hour, setHour] = useState(0);
  const [showHeat, setShowHeat] = useState(true);
  const [focus, setFocus] = useState<MapFocus | null>(null);

  // A new forecast starts again at departure
  useEffect(() => setHour(0), [heat.data]);

  // On phones, jump to the map when results arrive
  useEffect(() => {
    if (status === "success" && !isDesktop) setTab("map");
  }, [status, isDesktop]);

  const selectRoute = useCallback(
    (id: string) => {
      trip.setSelectedId(id);
      setFocus(null);
    },
    [trip],
  );

  const selectedRoute = analysis?.routes.find((r) => r.id === selectedId);
  const mapVisible = isDesktop || tab === "map";

  return (
    <div className="app" data-tab={tab}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ⛈
          </span>
          <div>
            <h1>SafeHaul</h1>
            <p>Weather-aware routing for truck drivers</p>
          </div>
        </div>
        <nav className="tabs" aria-label="View">
          <button type="button" className={tab === "plan" ? "is-on" : ""} aria-pressed={tab === "plan"} onClick={() => setTab("plan")}>
            Plan
          </button>
          <button type="button" className={tab === "map" ? "is-on" : ""} aria-pressed={tab === "map"} onClick={() => setTab("map")}>
            Map
          </button>
        </nav>
      </header>

      <aside className="panel">
        <TripForm loading={status === "loading"} onSubmit={trip.analyze} />

        {status === "loading" && <LoadingPanel />}
        {status === "error" && error && <ErrorBanner error={error} />}

        {status === "idle" && <Intro />}

        {analysis && (
          <>
            <RouteCards analysis={analysis} selectedId={selectedId} onSelect={selectRoute} />
            {selectedRoute && (
              <RouteDetail
                route={selectedRoute}
                onFocus={(index) => {
                  setFocus({ routeId: selectedRoute.id, index, nonce: Date.now() });
                  if (!isDesktop) setTab("map");
                }}
              />
            )}
          </>
        )}

        <footer className="credits">
          Forecasts by{" "}
          <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">
            Open-Meteo.com
          </a>{" "}
          (CC BY 4.0) · Routing and maps by Mapbox · Wind is {analysis?.meta.wind_metric ?? "sustained"} speed
        </footer>
      </aside>

      <main className="map-wrap">
        <Suspense fallback={<div className="map-fallback">Loading map…</div>}>
          <MapView
            analysis={analysis}
            selectedId={selectedId}
            onSelectRoute={selectRoute}
            heat={heat.data}
            hour={hour}
            showHeat={showHeat}
            focus={focus}
            visible={mapVisible}
          />
        </Suspense>

        {analysis && <RouteChips routes={analysis.routes} selectedId={selectedId} onSelect={selectRoute} />}
        {analysis && (
          <HeatmapControl
            heat={heat}
            hour={hour}
            onHour={setHour}
            show={showHeat}
            onToggle={setShowHeat}
            onRetry={trip.retryHeatmap}
          />
        )}
      </main>
    </div>
  );
}

function Intro() {
  return (
    <section className="intro" aria-label="How it works">
      <h2 className="section-title">How it works</h2>
      <ol>
        <li>Enter your trip, departure time and load weight.</li>
        <li>
          We compare 3 routes using the forecast for <b>when you'll actually be there</b>.
        </li>
        <li>You get the safest route, plus a 48-hour weather heatmap along the corridor.</li>
      </ol>
      <ul className="legend legend-inline" aria-label="Risk levels">
        {RISK_LEVELS.map((l) => (
          <li key={l.score}>
            <i className="dot" style={{ background: l.color }} />
            {l.label}
          </li>
        ))}
      </ul>
    </section>
  );
}

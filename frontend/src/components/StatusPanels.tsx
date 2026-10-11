import { useEffect, useState } from "react";
import type { ApiError } from "../api/client";

/** Shown while routes and weather are being analysed. Explains cold starts on free hosting. */
export function LoadingPanel() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 8000);
    return () => clearTimeout(t);
  }, []);
  return (
    <section className="loading" aria-live="polite" aria-busy="true">
      <div className="loading-head">
        <span className="spinner" aria-hidden="true" />
        <div>
          <strong>Finding routes and checking the weather…</strong>
          <p className="muted">Looking at 3 routes and the forecast for when you reach each checkpoint.</p>
        </div>
      </div>
      {slow && (
        <p className="note">
          The server may be waking up after being idle (free hosting). This can take up to a minute the first time.
        </p>
      )}
      {[0, 1, 2].map((i) => (
        <div className="skeleton-card" key={i} aria-hidden="true">
          <span className="sk sk-title" />
          <span className="sk sk-row" />
          <span className="sk sk-bar" />
        </div>
      ))}
    </section>
  );
}

export function ErrorBanner({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="banner banner-error" role="alert">
      <strong>{titleFor(error.code)}</strong>
      <span>{error.message}</span>
      {error.retryable && onRetry && (
        <button type="button" className="btn-secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

function titleFor(code: string): string {
  switch (code) {
    case "place_not_found":
      return "Place not found";
    case "no_route":
      return "No route found";
    case "forecast_unavailable":
      return "Forecast not available";
    case "upstream_unavailable":
    case "network":
    case "timeout":
      return "Couldn't complete the analysis";
    case "invalid_trip":
    case "invalid_request":
      return "Check the trip details";
    default:
      return "Something went wrong";
  }
}

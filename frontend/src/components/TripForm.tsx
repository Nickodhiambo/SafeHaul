import { useState } from "react";
import type { AnalyzeRequest, Place } from "../api/types";
import { toLocalInputValue, defaultDeparture } from "../lib/time";
import { validateTrip, type TripErrors, type TripFormState } from "../lib/trip";
import { PlaceInput } from "./PlaceInput";

interface Props {
  loading: boolean;
  onSubmit: (request: AnalyzeRequest) => void;
}

const LOAD_PRESETS = [
  { label: "Empty", lb: 10_000 },
  { label: "30k", lb: 30_000 },
  { label: "42k", lb: 42_000 },
  { label: "Max 80k", lb: 80_000 },
];

export function TripForm({ loading, onSubmit }: Props) {
  const [form, setForm] = useState<TripFormState>(() => ({
    originText: "",
    originPlace: null,
    destText: "",
    destPlace: null,
    departureLocal: defaultDeparture(),
    loadText: "42000",
  }));
  const [errors, setErrors] = useState<TripErrors>({});

  const patch = (p: Partial<TripFormState>, clear: (keyof TripErrors)[] = []) => {
    setForm((f) => ({ ...f, ...p }));
    if (clear.length) setErrors((e) => Object.fromEntries(Object.entries(e).filter(([k]) => !clear.includes(k as keyof TripErrors))));
  };

  const swap = () =>
    patch({
      originText: form.destText,
      originPlace: form.destPlace,
      destText: form.originText,
      destPlace: form.originPlace,
    });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    const result = validateTrip(form);
    setErrors(result.errors);
    if (result.request) onSubmit(result.request);
  };

  const setOrigin = (text: string, place: Place | null) =>
    patch({ originText: text, originPlace: place }, ["origin", "destination"]);
  const setDest = (text: string, place: Place | null) =>
    patch({ destText: text, destPlace: place }, ["destination"]);

  return (
    <form className="trip-form" onSubmit={submit} noValidate>
      <div className="endpoints">
        <PlaceInput
          label="Origin"
          marker="A"
          placeholder="City or address"
          value={form.originText}
          selected={form.originPlace}
          onChange={setOrigin}
          error={errors.origin}
        />
        <button type="button" className="swap-btn" onClick={swap} aria-label="Swap origin and destination" title="Swap">
          ⇅
        </button>
        <PlaceInput
          label="Destination"
          marker="B"
          placeholder="City or address"
          value={form.destText}
          selected={form.destPlace}
          onChange={setDest}
          error={errors.destination}
        />
      </div>

      <div className="field">
        <label htmlFor="departure" className="field-label">
          Departure
        </label>
        <input
          id="departure"
          className={`input${errors.departure ? " input-error" : ""}`}
          type="datetime-local"
          min={toLocalInputValue(new Date())}
          value={form.departureLocal}
          onChange={(e) => patch({ departureLocal: e.target.value }, ["departure"])}
          aria-invalid={errors.departure ? true : undefined}
          aria-describedby="departure-hint"
        />
        <p id="departure-hint" className="field-hint">
          Your local time. Weather is forecast for when you reach each checkpoint.
        </p>
        {errors.departure && (
          <p className="field-error" role="alert">
            {errors.departure}
          </p>
        )}
      </div>

      <div className="field">
        <label htmlFor="load" className="field-label">
          Load weight (lb)
        </label>
        <input
          id="load"
          className={`input${errors.load ? " input-error" : ""}`}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          value={form.loadText}
          onChange={(e) => patch({ loadText: e.target.value }, ["load"])}
          aria-invalid={errors.load ? true : undefined}
          aria-describedby="load-hint"
        />
        <div className="chips" role="group" aria-label="Load presets">
          {LOAD_PRESETS.map((p) => (
            <button
              key={p.lb}
              type="button"
              className={`chip${form.loadText.replace(/[,\s]/g, "") === String(p.lb) ? " is-on" : ""}`}
              onClick={() => patch({ loadText: String(p.lb) }, ["load"])}
            >
              {p.label}
            </button>
          ))}
        </div>
        <p id="load-hint" className="field-hint">
          Heavier loads are stricter in high wind (over 30,000 lb and 40,000 lb).
        </p>
        {errors.load && (
          <p className="field-error" role="alert">
            {errors.load}
          </p>
        )}
      </div>

      <button className="btn-primary" type="submit" disabled={loading}>
        {loading ? (
          <>
            <span className="spinner spinner-sm spinner-on-dark" aria-hidden="true" /> Analyzing…
          </>
        ) : (
          "Find the safest route"
        )}
      </button>
    </form>
  );
}

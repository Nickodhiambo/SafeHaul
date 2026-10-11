import { useEffect, useMemo, useRef, useState } from "react";
import type { HeatState } from "../hooks/useTrip";
import { levelInfo, RISK_LEVELS } from "../lib/risk";
import { addHours, formatDayTime } from "../lib/time";

interface Props {
  heat: HeatState;
  hour: number;
  onHour: (hour: number) => void;
  show: boolean;
  onToggle: (show: boolean) => void;
  onRetry: () => void;
}

const PLAY_INTERVAL_MS = 450;

/** Heatmap on/off, the 0-48 h forecast slider with play, and the colour legend. */
export function HeatmapControl({ heat, hour, onHour, show, onToggle, onRetry }: Props) {
  const data = heat.data;
  const [playing, setPlaying] = useState(false);
  const hourRef = useRef(hour);
  useEffect(() => {
    hourRef.current = hour;
  });

  // New data (new analysis): stop playing
  useEffect(() => setPlaying(false), [data]);

  useEffect(() => {
    if (!playing || !data) return;
    const id = window.setInterval(() => {
      const next = hourRef.current + 1;
      if (next > data.hours) setPlaying(false);
      else onHour(next);
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [playing, data, onHour]);

  const worst = useMemo(() => {
    if (!data) return 1;
    let max = 1;
    for (const p of data.points) if ((p.level[hour] ?? 1) > max) max = p.level[hour];
    return max;
  }, [data, hour]);

  const timeLabel = data ? formatDayTime(addHours(data.start, hour)) : "";
  const worstInfo = levelInfo(worst);

  return (
    <section className="heat-control" aria-label="Weather heatmap">
      <div className="heat-top">
        <label className="switch">
          <input type="checkbox" checked={show} onChange={(e) => onToggle(e.target.checked)} />
          <span>Weather heatmap</span>
        </label>
        {data && show && (
          <span className="heat-worst" aria-live="polite">
            Worst on the routes:{" "}
            <b className="dot-label">
              <i className="dot" style={{ background: worstInfo.color }} />
              {worstInfo.label}
            </b>
          </span>
        )}
      </div>

      {heat.status === "loading" && (
        <p className="heat-msg" role="status">
          <span className="spinner spinner-sm" aria-hidden="true" /> Loading the 48-hour forecast…
        </p>
      )}

      {heat.status === "error" && (
        <p className="heat-msg heat-msg-error" role="alert">
          The forecast heatmap couldn't load. Your routes are still valid.
          <button type="button" className="btn-link" onClick={onRetry}>
            Retry
          </button>
        </p>
      )}

      {data && (
        <div className={`slider-row${show ? "" : " is-off"}`}>
          <button
            type="button"
            className="play-btn"
            onClick={() => {
              if (hour >= data.hours) onHour(0);
              setPlaying((p) => !p);
            }}
            aria-label={playing ? "Pause forecast animation" : "Play forecast animation"}
            disabled={!show}
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <div className="slider-main">
            <input
              type="range"
              min={0}
              max={data.hours}
              step={1}
              value={Math.min(hour, data.hours)}
              disabled={!show}
              onChange={(e) => {
                setPlaying(false);
                onHour(Number(e.target.value));
              }}
              aria-label="Forecast hours after departure"
              aria-valuetext={`${hour === 0 ? "Departure" : `${hour} hours after departure`}, ${timeLabel}`}
            />
            <div className="slider-labels">
              <span>Departure</span>
              <span>+{data.hours} h</span>
            </div>
          </div>
          <div className="slider-time">
            <b>{timeLabel}</b>
            <small>{hour === 0 ? "at departure" : `+${hour} h`}</small>
          </div>
        </div>
      )}

      <ul className="legend" aria-label="Risk legend">
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

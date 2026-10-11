"""Weather-risk heatmap data for the trip corridor, for hours 0..48 after departure.

The frontend sends the corridor points it got from `/api/analyze` and receives, for every
point, the risk level and raw conditions at each hour. It loads everything once; moving the
forecast slider is then a pure client-side lookup (no network call per slider move).

Efficiency: all points go through `weather.load_series` in one batched, cached call (the
analysis that just ran has usually warmed the cache), and then each hour is a cheap array
lookup. Risk uses the same `assess_checkpoint` rules as the route analysis, including the load
rules, so the heatmap never disagrees with the checkpoint table.

Hour 0 is the departure time. If departure is so far ahead that 48 hours would run past the
16-day forecast window, the heatmap is shortened instead of failing; `hours` tells the
frontend how many steps are available.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence

from .risk import RiskLevel, assess_checkpoint
from .sampling import LatLon
from .weather import ForecastRangeError, GridKey, HourlySeries, grid_key, sample_at

MAX_POINTS = 400
MAX_HOURS = 48


class WeatherSeriesService(Protocol):
    wind_metric: str

    def load_series(
        self, keys: set[GridKey], need_start: datetime, need_end: datetime
    ) -> dict[GridKey, HourlySeries]: ...

    def latest_forecast_time(self) -> datetime: ...


def build_heatmap(
    points: Sequence[LatLon],
    start: datetime,
    load_lb: float,
    *,
    weather: WeatherSeriesService,
    hours: int = MAX_HOURS,
) -> dict:
    if not points:
        raise ValueError("at least one point is required")
    if len(points) > MAX_POINTS:
        raise ValueError(f"at most {MAX_POINTS} points are allowed")
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be between 1 and {MAX_HOURS}")
    if start.tzinfo is None:
        raise ValueError("start must be timezone-aware")
    start = start.astimezone(timezone.utc)

    # Shorten the window rather than fail if it runs past the forecast horizon
    latest = weather.latest_forecast_time()
    if start + timedelta(hours=hours) > latest:
        hours = int((latest - start).total_seconds() // 3600)
        if hours < 0:
            raise ForecastRangeError("Start time is beyond the available forecast window")

    frames = [start + timedelta(hours=h) for h in range(hours + 1)]
    series = weather.load_series({grid_key(lat, lon) for lat, lon in points}, start, frames[-1])

    out_points = []
    for lat, lon in points:
        s = series[grid_key(lat, lon)]
        levels, wind, rain, snow = [], [], [], []
        for when in frames:
            w = sample_at(s, when, weather.wind_metric)
            risk = assess_checkpoint(w.wind_mph, w.rain_in_hr, w.snow_in_hr, load_lb)
            levels.append(int(risk.level))
            wind.append(round(w.wind_mph, 1))
            rain.append(round(w.rain_in_hr, 3))
            snow.append(round(w.snow_in_hr, 3))
        out_points.append(
            {
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "level": levels,
                "wind_mph": wind,
                "rain_in_hr": rain,
                "snow_in_hr": snow,
            }
        )

    return {
        "start": start.isoformat(),
        "hours": hours,  # slider runs 0..hours
        "step_hours": 1,
        "load_lb": load_lb,
        "wind_metric": weather.wind_metric,
        "legend": {str(int(lvl)): lvl.label for lvl in RiskLevel},
        "points": out_points,
    }

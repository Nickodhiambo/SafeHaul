"""Weather lookup for (lat, lon, time) requests, backed by Open-Meteo.

Design goals: few HTTP calls, predictable units, easy to test.

    * One batched request per 50 distinct grid points (Open-Meteo accepts comma-separated
      coordinates and returns a list), fetched in parallel.
    * Coordinates are snapped to a 0.1 degree grid (~7 mi), finer than the model resolution,
      so nearby checkpoints and overlapping routes share one fetch and one cache entry.
    * Each fetch stores the whole hourly series for a point, so the same cache serves
      checkpoint lookups and the 0-48h heatmap.
    * Units are requested directly from the API: mph and inches (snowfall comes back in inches
      when precipitation_unit=inch). Hourly rain/snowfall values are "preceding hour sum",
      so they are already in/hr.
    * Rain rate = `rain` + `showers` (Open-Meteo's `rain` excludes showers).
    * The forecast hour used for a given ETA is the nearest hour (half-hours round up).
    * Missing (null) values are treated as 0.

Wind metric: `wind_mph` on a sample is sustained 10 m wind by default, or gusts if the client
is built with wind_metric="gust" (more conservative for trucks). Both are always kept on the
sample.
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"
GRID_DECIMALS = 1
MAX_FORECAST_DAYS = 16
BATCH_SIZE = 50
CACHE_TTL_S = 30 * 60
HOUR_S = 3600

GridKey = tuple[float, float]


class WeatherError(Exception):
    pass


class WeatherUnavailable(WeatherError):
    """Network/HTTP failure or malformed response from the weather provider."""


class ForecastRangeError(WeatherError):
    """Requested time is in the past or beyond the available forecast window."""


@dataclass(frozen=True)
class WeatherSample:
    time: datetime  # forecast hour actually used (UTC)
    wind_mph: float  # value used for risk (sustained or gust, per client setting)
    gust_mph: float
    rain_in_hr: float
    snow_in_hr: float

    def to_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "wind_mph": round(self.wind_mph, 1),
            "gust_mph": round(self.gust_mph, 1),
            "rain_in_hr": round(self.rain_in_hr, 3),
            "snow_in_hr": round(self.snow_in_hr, 3),
        }


@dataclass(frozen=True)
class HourlySeries:
    start_ts: int  # unix seconds of first hour
    wind: tuple[float, ...]
    gust: tuple[float, ...]
    rain: tuple[float, ...]  # rain + showers
    snow: tuple[float, ...]

    @property
    def end_ts(self) -> int:
        return self.start_ts + HOUR_S * (len(self.wind) - 1)

    def covers(self, ts: float) -> bool:
        return self.start_ts - HOUR_S / 2 <= ts < self.end_ts + HOUR_S / 2


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def grid_key(lat: float, lon: float) -> GridKey:
    return (round(lat, GRID_DECIMALS), round(lon, GRID_DECIMALS))


def parse_series(entry: dict) -> HourlySeries:
    try:
        h = entry["hourly"]
        times = h["time"]
        n = len(times)
        if n == 0:
            raise ValueError("empty series")
        if n > 1 and times[1] - times[0] != HOUR_S:
            raise ValueError("series is not hourly")

        def col(name: str) -> list[float]:
            vals = h[name]
            if len(vals) != n:
                raise ValueError(f"{name} length mismatch")
            return [0.0 if v is None else float(v) for v in vals]

        showers = col("showers")
        return HourlySeries(
            start_ts=int(times[0]),
            wind=tuple(col("wind_speed_10m")),
            gust=tuple(col("wind_gusts_10m")),
            rain=tuple(r + s for r, s in zip(col("rain"), showers)),
            snow=tuple(col("snowfall")),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise WeatherUnavailable(f"Unexpected weather response: {e}") from e


def sample_at(series: HourlySeries, when: datetime, wind_metric: str = "sustained") -> WeatherSample:
    """Weather at the forecast hour nearest to `when`."""
    ts = when.timestamp()
    if not series.covers(ts):
        raise ForecastRangeError(
            f"{when.isoformat()} is outside the available forecast window"
        )
    idx = min(max(math.floor((ts - series.start_ts) / HOUR_S + 0.5), 0), len(series.wind) - 1)
    gust = series.gust[idx]
    wind = gust if wind_metric == "gust" else series.wind[idx]
    return WeatherSample(
        time=datetime.fromtimestamp(series.start_ts + idx * HOUR_S, tz=timezone.utc),
        wind_mph=wind,
        gust_mph=gust,
        rain_in_hr=series.rain[idx],
        snow_in_hr=series.snow[idx],
    )


# ---------------------------------------------------------------------------
# HTTP + cache
# ---------------------------------------------------------------------------
def default_http_get(url: str, params: dict, timeout: float = 15):
    import requests  # imported lazily so unit tests don't need it

    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        raise WeatherUnavailable(f"Weather request failed: {e}") from e
    if resp.status_code != 200:
        raise WeatherUnavailable(f"Open-Meteo returned HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


class TTLCache:
    """Minimal thread-safe in-memory cache. Swap for Django's cache/Redis if you scale out."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if self._clock() >= expires:
                del self._data[key]
                return None
            return value

    def set(self, key, value, ttl_s: float):
        with self._lock:
            self._data[key] = (self._clock() + ttl_s, value)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class WeatherClient:
    def __init__(
        self,
        *,
        http_get: Callable[[str, dict], object] = default_http_get,
        cache: TTLCache | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
        wind_metric: str = "sustained",
        batch_size: int = BATCH_SIZE,
        ttl_s: float = CACHE_TTL_S,
        retries: int = 2,
    ):
        if wind_metric not in ("sustained", "gust"):
            raise ValueError("wind_metric must be 'sustained' or 'gust'")
        self._http_get = http_get
        self._cache = cache or TTLCache()
        self._now = now
        self._sleep = sleep
        self.wind_metric = wind_metric
        self._batch_size = batch_size
        self._ttl_s = ttl_s
        self._retries = retries

    # -- public ------------------------------------------------------------
    def get_weather(self, requests: Sequence[tuple[float, float, datetime]]) -> list[WeatherSample]:
        """Weather for each (lat, lon, when) in order. `when` must be timezone-aware."""
        if not requests:
            return []
        if any(w.tzinfo is None for _, _, w in requests):
            raise ValueError("times must be timezone-aware")

        keys = {grid_key(lat, lon) for lat, lon, _ in requests}
        need_start = min(w for _, _, w in requests)
        need_end = max(w for _, _, w in requests)
        series = self.load_series(keys, need_start, need_end)
        return [sample_at(series[grid_key(lat, lon)], w, self.wind_metric) for lat, lon, w in requests]

    def load_series(self, keys: set[GridKey], need_start: datetime, need_end: datetime) -> dict[GridKey, HourlySeries]:
        """Hourly series per grid point covering [need_start, need_end] (cached, batched)."""
        days = self._forecast_days(need_end)
        found: dict[GridKey, HourlySeries] = {}
        missing: list[GridKey] = []
        for key in sorted(keys):
            cached = self._cache.get(key)
            if cached is not None and cached.covers(need_start.timestamp()) and cached.covers(need_end.timestamp()):
                found[key] = cached
            else:
                missing.append(key)

        chunks = [missing[i : i + self._batch_size] for i in range(0, len(missing), self._batch_size)]
        if chunks:
            with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
                results = list(pool.map(lambda c: self._fetch(c, days), chunks))
            for chunk, entries in zip(chunks, results):
                for key, entry in zip(chunk, entries):
                    s = parse_series(entry)
                    self._cache.set(key, s, self._ttl_s)
                    found[key] = s
        return found

    # -- internals ---------------------------------------------------------
    def _forecast_days(self, need_end: datetime) -> int:
        today = self._now().astimezone(timezone.utc).date()
        days = (need_end.astimezone(timezone.utc).date() - today).days + 1
        if days > MAX_FORECAST_DAYS:
            raise ForecastRangeError(
                f"Forecast is only available up to {MAX_FORECAST_DAYS} days ahead"
            )
        return max(days, 1)

    def _fetch(self, keys: list[GridKey], days: int) -> list[dict]:
        params = {
            "latitude": ",".join(f"{lat:.{GRID_DECIMALS}f}" for lat, _ in keys),
            "longitude": ",".join(f"{lon:.{GRID_DECIMALS}f}" for _, lon in keys),
            "hourly": HOURLY_VARS,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "timeformat": "unixtime",
            "forecast_days": days,
        }
        payload = self._with_retries(lambda: self._http_get(OPEN_METEO_URL, params))
        entries = [payload] if isinstance(payload, dict) else payload
        if not isinstance(entries, list) or len(entries) != len(keys):
            raise WeatherUnavailable("Weather response did not match the requested points")
        return entries

    def _with_retries(self, call):
        for attempt in range(self._retries + 1):
            try:
                return call()
            except WeatherUnavailable:
                if attempt == self._retries:
                    raise
                self._sleep(0.5 * 2**attempt)

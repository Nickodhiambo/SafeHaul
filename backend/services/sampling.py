"""Checkpoint sampling along a route. Pure functions.

Given a route polyline, produce checkpoints at a fixed mile spacing, each with a position
(lat/lon), cumulative miles from the origin, and the truck's estimated arrival time.

Conventions:
    * Coordinates are (lat, lon) tuples. Routing APIs return GeoJSON (lon, lat);
      convert with `from_geojson_coords`.
    * Departure must be a timezone-aware datetime (convert to UTC before calling).

Spacing rule (the brief says "every 10 / 25 / 50 miles"; we read that as adaptive):
    route < 150 mi   -> every 10 mi
    150-500 mi       -> every 25 mi
    route > 500 mi   -> every 50 mi

Checkpoint set always includes the origin (mile 0) and the destination (final mile).
An intermediate checkpoint closer than 25% of the spacing to the destination is dropped
so we never sample two nearly identical points at the end.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Sequence

EARTH_RADIUS_MI = 3958.7613
SHORT_ROUTE_MAX_MI = 150
MEDIUM_ROUTE_MAX_MI = 500
MIN_END_GAP_FRACTION = 0.25

LatLon = tuple[float, float]


@dataclass(frozen=True)
class Checkpoint:
    index: int
    distance_mi: float  # cumulative miles from origin
    lat: float
    lon: float
    elapsed_s: float  # seconds since departure
    eta: datetime  # timezone-aware

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "distance_mi": round(self.distance_mi, 1),
            "lat": round(self.lat, 5),
            "lon": round(self.lon, 5),
            "elapsed_s": round(self.elapsed_s),
            "eta": self.eta.isoformat(),
        }


def from_geojson_coords(coords: Sequence[Sequence[float]]) -> list[LatLon]:
    """GeoJSON [lon, lat, ...] -> (lat, lon)."""
    return [(c[1], c[0]) for c in coords]


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * asin(sqrt(h))


def choose_spacing_mi(total_distance_mi: float) -> int:
    if total_distance_mi < SHORT_ROUTE_MAX_MI:
        return 10
    if total_distance_mi <= MEDIUM_ROUTE_MAX_MI:
        return 25
    return 50


def _cumulative(values: Sequence[float]) -> list[float]:
    out = [0.0]
    for v in values:
        out.append(out[-1] + v)
    return out


def _interpolate(target: float, cum: list[float], coords: Sequence[LatLon], cum_t: list[float]):
    """Position and elapsed time at `target` miles along the route."""
    i = min(max(bisect_right(cum, target) - 1, 0), len(coords) - 2)
    seg = cum[i + 1] - cum[i]
    f = (target - cum[i]) / seg if seg > 0 else 0.0
    f = min(max(f, 0.0), 1.0)
    lat = coords[i][0] + f * (coords[i + 1][0] - coords[i][0])
    lon = coords[i][1] + f * (coords[i + 1][1] - coords[i][1])
    t = cum_t[i] + f * (cum_t[i + 1] - cum_t[i])
    return lat, lon, t


def generate_checkpoints(
    coords: Sequence[LatLon],
    departure: datetime,
    *,
    total_distance_mi: float | None = None,
    total_duration_s: float | None = None,
    segment_durations_s: Sequence[float] | None = None,
    spacing_mi: float | None = None,
) -> list[Checkpoint]:
    """Sample checkpoints along `coords`.

    total_distance_mi   routing API's reported distance; geometry distances are scaled to match
    total_duration_s    routing API's reported duration
    segment_durations_s optional per-segment durations (len(coords)-1), e.g. Mapbox annotations;
                        gives realistic ETAs when speed varies. If omitted, speed is assumed
                        constant along the route.
    spacing_mi          override the adaptive spacing (mainly for tests and the heatmap)
    """
    if departure.tzinfo is None:
        raise ValueError("departure must be timezone-aware")
    if len(coords) < 2:
        raise ValueError("route needs at least two coordinates")

    cum = _cumulative([haversine_mi(coords[i], coords[i + 1]) for i in range(len(coords) - 1)])
    if cum[-1] <= 0:
        raise ValueError("route has zero length")
    if total_distance_mi is not None:
        scale = total_distance_mi / cum[-1]
        cum = [c * scale for c in cum]
    total = cum[-1]

    if segment_durations_s is not None:
        if len(segment_durations_s) != len(coords) - 1:
            raise ValueError("segment_durations_s must have len(coords) - 1 entries")
        cum_t = _cumulative(segment_durations_s)
        if total_duration_s is not None and cum_t[-1] > 0:
            cum_t = [t * total_duration_s / cum_t[-1] for t in cum_t]
    elif total_duration_s is not None:
        cum_t = [total_duration_s * c / total for c in cum]
    else:
        raise ValueError("provide total_duration_s or segment_durations_s")

    spacing = spacing_mi or choose_spacing_mi(total)
    targets = [0.0]
    k = 1
    while k * spacing < total:
        targets.append(k * spacing)
        k += 1
    if len(targets) > 1 and total - targets[-1] < spacing * MIN_END_GAP_FRACTION:
        targets.pop()
    targets.append(total)

    checkpoints = []
    for idx, d in enumerate(targets):
        lat, lon, elapsed = _interpolate(d, cum, coords, cum_t)
        checkpoints.append(
            Checkpoint(
                index=idx,
                distance_mi=d,
                lat=lat,
                lon=lon,
                elapsed_s=elapsed,
                eta=departure + timedelta(seconds=elapsed),
            )
        )
    return checkpoints

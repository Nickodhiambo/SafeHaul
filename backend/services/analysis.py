"""Trip analysis: the one place where all the services are wired together.

    routes -> checkpoints (+ETAs) -> weather -> risk per checkpoint -> route stats -> ranking

Dependencies (`routing`, `weather`) are passed in, so this is fully testable with fakes and
has no Django imports. The Django view only validates input and maps errors to HTTP codes.

All weather lookups for all routes go out in a single `weather.get_weather` call so the
client can batch and deduplicate (routes share their start and end areas).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Sequence

from .geometry import simplify_path
from .recommend import CheckpointRisk, RouteInput, recommend_route
from .risk import assess_checkpoint
from .routing import Route
from .sampling import LatLon, generate_checkpoints, haversine_mi
from .weather import WeatherSample, grid_key

MIN_TRIP_MILES = 0.1
CORRIDOR_POINTS_PER_ROUTE = 70
MIN_CORRIDOR_SPACING_MI = 5.0


class InvalidTrip(ValueError):
    """The request is well-formed but the trip itself doesn't make sense."""


@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    label: str = ""

    @property
    def point(self) -> LatLon:
        return (self.lat, self.lon)

    def to_dict(self) -> dict:
        return {"lat": self.lat, "lon": self.lon, "label": self.label}


class RoutingService(Protocol):
    def get_routes(self, origin: LatLon, destination: LatLon) -> list[Route]: ...


class WeatherService(Protocol):
    wind_metric: str

    def get_weather(
        self, requests: Sequence[tuple[float, float, datetime]]
    ) -> list[WeatherSample]: ...


def corridor_points(routes: Sequence[Route], departure: datetime) -> list[dict]:
    """Evenly spaced points along every route for the heatmap, one per ~7 mi weather cell.

    Denser than the risk checkpoints (which follow the 10/25/50 mi rule) so the heatmap looks
    continuous; points sharing a weather grid cell are merged since they'd have identical data.
    """
    seen, points = set(), []
    for r in routes:
        spacing = max(MIN_CORRIDOR_SPACING_MI, r.distance_mi / CORRIDOR_POINTS_PER_ROUTE)
        for cp in generate_checkpoints(
            r.coords,
            departure,
            total_distance_mi=r.distance_mi,
            total_duration_s=r.duration_s,
            segment_durations_s=r.segment_durations_s,
            spacing_mi=spacing,
        ):
            key = grid_key(cp.lat, cp.lon)
            if key not in seen:
                seen.add(key)
                points.append({"lat": round(cp.lat, 4), "lon": round(cp.lon, 4)})
    return points


def analyze_trip(
    origin: Location,
    destination: Location,
    departure: datetime,
    load_lb: float,
    *,
    routing: RoutingService,
    weather: WeatherService,
) -> dict:
    """Analyze every route option and recommend one. Returns a JSON-serializable dict."""
    if departure.tzinfo is None:
        raise InvalidTrip("departure must include a timezone")
    if load_lb < 0:
        raise InvalidTrip("load weight cannot be negative")
    if haversine_mi(origin.point, destination.point) < MIN_TRIP_MILES:
        raise InvalidTrip("Origin and destination are the same place")
    departure = departure.astimezone(timezone.utc)

    # 1. Route options and their checkpoints with ETAs
    routes = routing.get_routes(origin.point, destination.point)
    checkpoints_by_route = [
        generate_checkpoints(
            r.coords,
            departure,
            total_distance_mi=r.distance_mi,
            total_duration_s=r.duration_s,
            segment_durations_s=r.segment_durations_s,
        )
        for r in routes
    ]

    # 2. One batched weather call for every checkpoint on every route
    samples = iter(
        weather.get_weather([(cp.lat, cp.lon, cp.eta) for cps in checkpoints_by_route for cp in cps])
    )

    # 3. Risk at each checkpoint
    analyzed: list[list[tuple]] = []
    for cps in checkpoints_by_route:
        rows = []
        for cp in cps:
            sample = next(samples)
            risk = assess_checkpoint(sample.wind_mph, sample.rain_in_hr, sample.snow_in_hr, load_lb)
            rows.append((cp, sample, risk))
        analyzed.append(rows)

    # 4. Route stats and ranking
    recommendation = recommend_route(
        [
            RouteInput(
                route_id=r.route_id,
                total_distance_mi=r.distance_mi,
                duration_s=r.duration_s,
                checkpoints=tuple(CheckpointRisk(cp.distance_mi, risk.level) for cp, _, risk in rows),
            )
            for r, rows in zip(routes, analyzed)
        ]
    )

    # 5. Response, best route first
    by_id = {r.route_id: (r, rows) for r, rows in zip(routes, analyzed)}
    route_payloads = []
    for ranked in recommendation.ranked:
        route, rows = by_id[ranked.stats.route_id]
        route_payloads.append(
            {
                "id": route.route_id,
                "summary": route.summary or f"Route {route.route_id.split('-')[-1]}",
                "rank": ranked.rank,
                "recommended": ranked.recommended,
                "distance_mi": round(route.distance_mi, 1),
                "duration_s": round(route.duration_s),
                "arrival": rows[-1][0].eta.isoformat(),
                "stats": ranked.stats.to_dict(),
                "geometry": [
                    [round(lon, 5), round(lat, 5)] for lat, lon in simplify_path(route.coords)
                ],
                "checkpoints": [
                    {**cp.to_dict(), "weather": sample.to_dict(), "risk": risk.to_dict()}
                    for cp, sample, risk in rows
                ],
            }
        )

    return {
        "request": {
            "origin": origin.to_dict(),
            "destination": destination.to_dict(),
            "departure": departure.isoformat(),
            "load_lb": load_lb,
        },
        "recommended_route_id": recommendation.best.stats.route_id,
        "recommendation": {"summary": recommendation.summary},
        "routes": route_payloads,
        "corridor": corridor_points(routes, departure),
        "meta": {
            "wind_metric": weather.wind_metric,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    }

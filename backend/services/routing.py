"""Route options from the Mapbox Directions API.

`RoutingClient.get_routes(origin, destination)` returns up to 3 `Route` objects, each in the
shape `sampling.generate_checkpoints` expects (lat/lon coords, miles, seconds and optional
per-segment durations).

How we get 3 routes:
    1. One request with alternatives=true. Mapbox returns the fastest route plus up to two
       alternatives, but often returns fewer on simple trips.
    2. If fewer than 3 came back, request detours: origin -> via -> destination, where `via`
       is offset sideways from the midpoint. A detour is kept only if it is genuinely
       different from the routes we already have (>= 20% of its length is far from all of
       them) and not absurdly longer (<= 1.75x the fastest route's duration).

Limitation worth stating in the README: Mapbox has no truck profile, so this uses
`mapbox/driving`. Truck restrictions (height/weight) are not applied.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from math import cos, degrees, hypot, radians
from typing import Callable, Sequence

from .sampling import EARTH_RADIUS_MI, LatLon, from_geojson_coords, haversine_mi

DIRECTIONS_URL = "https://api.mapbox.com/directions/v5"
METERS_PER_MILE = 1609.344

MAX_ROUTES = 3
DETOUR_OFFSET_FRACTIONS = (0.2, 0.35)  # sideways offset as a share of the straight-line distance
MIN_DETOUR_OFFSET_MI = 3.0
MAX_DETOUR_DURATION_RATIO = 1.75
MIN_DISTINCT_SHARE = 0.2
DISTINCT_SAMPLES = 25
EXISTING_VERTEX_CAP = 300


class RoutingError(Exception):
    pass


class NoRouteFound(RoutingError):
    pass


class RoutingUnavailable(RoutingError):
    """Network failure, rate limit or server error from the routing provider."""


@dataclass(frozen=True)
class Route:
    route_id: str
    coords: tuple[LatLon, ...]  # (lat, lon)
    distance_mi: float
    duration_s: float
    segment_durations_s: tuple[float, ...] | None  # len(coords) - 1, or None if unavailable
    summary: str  # e.g. "I-80, I-90"

    def geojson_coords(self) -> list[list[float]]:
        return [[lon, lat] for lat, lon in self.coords]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse_route(raw: dict) -> Route:
    try:
        coords = tuple(from_geojson_coords(raw["geometry"]["coordinates"]))
        if len(coords) < 2:
            raise ValueError("geometry too short")

        legs = raw.get("legs") or []
        segs: list[float] | None = []
        for leg in legs:
            durations = (leg.get("annotation") or {}).get("duration")
            if durations is None:
                segs = None
                break
            segs.extend(float(d) for d in durations)
        if segs is not None and len(segs) != len(coords) - 1:
            segs = None  # annotations don't line up with the geometry; fall back to constant speed

        summary = ", ".join(s for s in (leg.get("summary") for leg in legs) if s)
        return Route(
            route_id="",
            coords=coords,
            distance_mi=float(raw["distance"]) / METERS_PER_MILE,
            duration_s=float(raw["duration"]),
            segment_durations_s=tuple(segs) if segs else None,
            summary=summary,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise RoutingUnavailable(f"Unexpected routing response: {e}") from e


# ---------------------------------------------------------------------------
# Detour helpers (pure)
# ---------------------------------------------------------------------------
def via_candidates(origin: LatLon, destination: LatLon, offset_mi: float) -> list[LatLon]:
    """Two points offset `offset_mi` to either side of the midpoint, perpendicular to the trip."""
    mid_lat = (origin[0] + destination[0]) / 2
    mid_lon = (origin[1] + destination[1]) / 2
    kx = max(cos(radians(mid_lat)), 1e-6)  # shrink longitude degrees to match latitude degrees
    dx = (destination[1] - origin[1]) * kx
    dy = destination[0] - origin[0]
    norm = hypot(dx, dy)
    if norm == 0:
        raise ValueError("origin and destination are the same")
    px, py = -dy / norm, dx / norm
    off_deg = degrees(offset_mi / EARTH_RADIUS_MI)
    return [
        (mid_lat + sign * py * off_deg, mid_lon + sign * px * off_deg / kx) for sign in (1, -1)
    ]


def _downsample(coords: Sequence[LatLon], cap: int) -> list[LatLon]:
    if len(coords) <= cap:
        return list(coords)
    stride = -(-len(coords) // cap)
    out = list(coords[::stride])
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


def distinct_share(candidate: Route, existing: Sequence[Route]) -> float:
    """Share of the candidate's interior points that are far from every existing route."""
    threshold = max(0.5, min(3.0, 0.08 * candidate.distance_mi))
    refs = [_downsample(r.coords, EXISTING_VERTEX_CAP) for r in existing]
    n = len(candidate.coords)
    idxs = sorted({int(n * (0.1 + 0.8 * i / (DISTINCT_SAMPLES - 1))) for i in range(DISTINCT_SAMPLES)})
    far = 0
    for i in idxs:
        p = candidate.coords[min(i, n - 1)]
        if all(min(haversine_mi(p, q) for q in ref) > threshold for ref in refs):
            far += 1
    return far / len(idxs)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def default_http_get(url: str, params: dict, timeout: float = 20):
    import requests  # lazy so unit tests don't need it

    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        # str(e) can contain the request URL (and token), so don't include it
        raise RoutingUnavailable(f"Routing request failed ({type(e).__name__})") from None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code in (401, 403):
        raise RoutingError("Mapbox rejected the access token")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RoutingUnavailable(f"Routing service returned HTTP {resp.status_code}")
    try:
        message = resp.json().get("message", "")
    except ValueError:
        message = ""
    raise RoutingError(f"Routing request rejected (HTTP {resp.status_code}): {message}".strip())


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class RoutingClient:
    def __init__(
        self,
        token: str,
        *,
        http_get: Callable[[str, dict], object] = default_http_get,
        profile: str = "mapbox/driving",
        max_routes: int = MAX_ROUTES,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 2,
    ):
        if not token:
            raise RoutingError("MAPBOX_TOKEN is not configured")
        self._token = token
        self._http_get = http_get
        self._profile = profile
        self._max_routes = max_routes
        self._sleep = sleep
        self._retries = retries

    def get_routes(self, origin: LatLon, destination: LatLon) -> list[Route]:
        if haversine_mi(origin, destination) < 0.1:
            raise ValueError("origin and destination are the same place")

        routes = [parse_route(r) for r in self._request([origin, destination], alternatives=True)]
        routes = routes[: self._max_routes]
        if not routes:
            raise NoRouteFound("No drivable route found between those places")
        if len(routes) < self._max_routes:
            routes = self._fill_with_detours(origin, destination, routes)
        return [replace(r, route_id=f"route-{i + 1}") for i, r in enumerate(routes)]

    # -- internals ---------------------------------------------------------
    def _request(self, waypoints: Sequence[LatLon], alternatives: bool) -> list[dict]:
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
        url = f"{DIRECTIONS_URL}/{self._profile}/{coords}"
        params = {
            "alternatives": "true" if alternatives else "false",
            "geometries": "geojson",
            "overview": "full",
            "annotations": "duration",
            "steps": "false",
            "access_token": self._token,
        }
        payload = self._with_retries(lambda: self._http_get(url, params))
        code = payload.get("code") if isinstance(payload, dict) else None
        if code in ("NoRoute", "NoSegment"):
            raise NoRouteFound(payload.get("message") or "No drivable route found")
        if code != "Ok":
            raise RoutingError(f"Routing failed: {payload.get('message', code) if isinstance(payload, dict) else 'bad response'}")
        return payload.get("routes") or []

    def _with_retries(self, call):
        for attempt in range(self._retries + 1):
            try:
                return call()
            except RoutingUnavailable:
                if attempt == self._retries:
                    raise
                self._sleep(0.5 * 2**attempt)

    def _fill_with_detours(self, origin: LatLon, destination: LatLon, routes: list[Route]) -> list[Route]:
        straight = haversine_mi(origin, destination)
        fastest = min(r.duration_s for r in routes)
        for fraction in DETOUR_OFFSET_FRACTIONS:
            for via in via_candidates(origin, destination, max(MIN_DETOUR_OFFSET_MI, fraction * straight)):
                if len(routes) >= self._max_routes:
                    return routes
                try:
                    raw = self._request([origin, via, destination], alternatives=False)
                except (NoRouteFound, RoutingUnavailable):
                    continue  # a failed detour must not break the routes we already have
                if not raw:
                    continue
                candidate = parse_route(raw[0])
                if candidate.duration_s > MAX_DETOUR_DURATION_RATIO * fastest:
                    continue
                if distinct_share(candidate, routes) >= MIN_DISTINCT_SHARE:
                    routes.append(candidate)
        return routes

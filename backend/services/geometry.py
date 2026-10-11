"""Route geometry simplification (Douglas-Peucker). Pure functions.

Mapbox returns full-resolution geometry: a cross-country route can have 10,000+ vertices.
Sending three of those to the browser makes the response heavy and the map sluggish.
Simplifying to a ~50 m tolerance is visually identical at any zoom a driver would use.

Used for the *drawn* line only. Checkpoint sampling and ETAs always use the full geometry.
"""
from __future__ import annotations

from math import cos, hypot, radians
from typing import Sequence

from .sampling import LatLon

MILES_PER_DEG_LAT = 69.05
MILES_PER_DEG_LON_EQUATOR = 69.17


def _project(coords: Sequence[LatLon]) -> list[tuple[float, float]]:
    """Flat local approximation in miles (fine for simplification tolerances)."""
    kx = cos(radians(sum(c[0] for c in coords) / len(coords))) * MILES_PER_DEG_LON_EQUATOR
    return [(c[1] * kx, c[0] * MILES_PER_DEG_LAT) for c in coords]


def _dist_to_segment(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _keep_mask(pts: list[tuple[float, float]], tol: float) -> list[bool]:
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]  # iterative: deep recursion would overflow on long routes
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        worst, worst_k = 0.0, -1
        for k in range(i + 1, j):
            d = _dist_to_segment(pts[k], a, b)
            if d > worst:
                worst, worst_k = d, k
        if worst > tol:
            keep[worst_k] = True
            stack.append((i, worst_k))
            stack.append((worst_k, j))
    return keep


def simplify_path(
    coords: Sequence[LatLon], tolerance_mi: float = 0.03, max_points: int = 2500
) -> list[LatLon]:
    """Drop vertices that deviate less than `tolerance_mi` from the simplified line.

    Endpoints are always kept. If the result still exceeds `max_points`, the tolerance is
    doubled until it fits.
    """
    if len(coords) <= 2:
        return list(coords)
    pts = _project(coords)
    tol = tolerance_mi
    keep = _keep_mask(pts, tol)
    for _ in range(12):
        if sum(keep) <= max_points:
            break
        tol *= 2
        keep = _keep_mask(pts, tol)
    return [c for c, k in zip(coords, keep) if k]

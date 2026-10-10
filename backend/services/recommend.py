"""Route statistics and recommendation. Pure functions, no I/O.

Each checkpoint "owns" a stretch of road: from the midpoint between it and the previous
checkpoint to the midpoint between it and the next one (the first owns from mile 0, the
last owns to the end of the route). Summing owned stretches by risk level gives
"Severe miles", "High miles", etc., and the mileage-weighted average risk.

Ranking follows the brief, strictly in this order (lower is better at every step):
    1. Fewest Severe miles
    2. Fewest High miles
    3. Lowest average risk
    4. Shortest travel time
Routes containing No Travel stretches are treated as blocked: fewer No Travel miles
always wins first, so any route with zero No Travel miles beats any route with some.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .risk import RiskLevel

# Miles/risk are compared at this precision so float noise never decides a ranking.
_MILES_PRECISION = 2
_RISK_PRECISION = 3


@dataclass(frozen=True)
class CheckpointRisk:
    distance_mi: float  # cumulative miles from origin
    level: RiskLevel


@dataclass(frozen=True)
class RouteInput:
    route_id: str
    total_distance_mi: float
    duration_s: float
    checkpoints: tuple[CheckpointRisk, ...]


@dataclass(frozen=True)
class RouteStats:
    route_id: str
    total_distance_mi: float
    duration_s: float
    miles_by_level: dict[RiskLevel, float]
    average_risk: float  # mileage-weighted, 1 (Low) .. 5 (No Travel)
    max_level: RiskLevel

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]

    @property
    def blocked(self) -> bool:
        return round(self.no_travel_miles, _MILES_PRECISION) > 0

    def sort_key(self) -> tuple:
        return (
            round(self.no_travel_miles, _MILES_PRECISION),
            round(self.severe_miles, _MILES_PRECISION),
            round(self.high_miles, _MILES_PRECISION),
            round(self.average_risk, _RISK_PRECISION),
            round(self.duration_s),
        )

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "total_distance_mi": round(self.total_distance_mi, 1),
            "duration_s": round(self.duration_s),
            "miles_by_level": {lvl.label: round(m, 1) for lvl, m in self.miles_by_level.items()},
            "no_travel_miles": round(self.no_travel_miles, 1),
            "severe_miles": round(self.severe_miles, 1),
            "high_miles": round(self.high_miles, 1),
            "average_risk": round(self.average_risk, 2),
            "max_level": self.max_level.label,
            "blocked": self.blocked,
        }


@dataclass(frozen=True)
class RankedRoute:
    stats: RouteStats
    rank: int  # 1 = best
    recommended: bool


@dataclass(frozen=True)
class Recommendation:
    ranked: tuple[RankedRoute, ...]
    summary: str = field(default="")

    @property
    def best(self) -> RankedRoute:
        return self.ranked[0]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def attribute_miles(checkpoints: tuple[CheckpointRisk, ...], total_distance_mi: float) -> list[float]:
    """Miles of road owned by each checkpoint. The result always sums to total_distance_mi."""
    n = len(checkpoints)
    if n == 0:
        return []
    d = [min(max(c.distance_mi, 0.0), total_distance_mi) for c in checkpoints]
    if any(b < a for a, b in zip(d, d[1:])):
        raise ValueError("checkpoints must be ordered by distance")

    owned = []
    for i in range(n):
        lo = 0.0 if i == 0 else (d[i - 1] + d[i]) / 2
        hi = total_distance_mi if i == n - 1 else (d[i] + d[i + 1]) / 2
        owned.append(hi - lo)
    return owned


def compute_route_stats(route: RouteInput) -> RouteStats:
    if not route.checkpoints:
        raise ValueError(f"route {route.route_id} has no checkpoints")
    if route.total_distance_mi < 0 or route.duration_s < 0:
        raise ValueError("distance and duration must be non-negative")

    owned = attribute_miles(route.checkpoints, route.total_distance_mi)
    miles_by_level = {lvl: 0.0 for lvl in RiskLevel}
    for cp, miles in zip(route.checkpoints, owned):
        miles_by_level[cp.level] += miles

    total = sum(owned)
    if total > 0:
        average = sum(int(cp.level) * m for cp, m in zip(route.checkpoints, owned)) / total
    else:  # zero-length route: fall back to a plain mean
        average = sum(int(cp.level) for cp in route.checkpoints) / len(route.checkpoints)

    return RouteStats(
        route_id=route.route_id,
        total_distance_mi=route.total_distance_mi,
        duration_s=route.duration_s,
        miles_by_level=miles_by_level,
        average_risk=average,
        max_level=max(cp.level for cp in route.checkpoints),
    )


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def recommend_route(routes: list[RouteInput]) -> Recommendation:
    if not routes:
        raise ValueError("at least one route is required")

    stats = [compute_route_stats(r) for r in routes]
    ordered = sorted(stats, key=RouteStats.sort_key)  # stable: ties keep input order
    ranked = tuple(
        RankedRoute(stats=s, rank=i + 1, recommended=(i == 0)) for i, s in enumerate(ordered)
    )
    return Recommendation(ranked=ranked, summary=_explain(ordered))


_CRITERIA = (
    ("fewest No Travel miles", lambda s: s.no_travel_miles, "mi"),
    ("fewest Severe miles", lambda s: s.severe_miles, "mi"),
    ("fewest High miles", lambda s: s.high_miles, "mi"),
    ("lowest average risk", lambda s: s.average_risk, ""),
    ("shortest travel time", lambda s: s.duration_s / 60, "min"),
)


def _fmt(value: float, unit: str) -> str:
    return f"{value:.2f}" if unit == "" else f"{value:.1f} {unit}"


def _explain(ordered: list[RouteStats]) -> str:
    best = ordered[0]
    if best.blocked:
        return (
            "Every route has No Travel conditions. This one has the least "
            f"({best.no_travel_miles:.1f} mi); delaying departure is strongly advised."
        )
    if len(ordered) == 1:
        return "Only one route available."

    runner_up = ordered[1]
    for (label, getter, unit), a, b in zip(_CRITERIA, best.sort_key(), runner_up.sort_key()):
        if a != b:
            return (
                f"Recommended for {label}: {_fmt(getter(best), unit)} vs "
                f"{_fmt(getter(runner_up), unit)} on the next best route."
            )
    return "Routes are equivalent on all criteria; picked the first returned."

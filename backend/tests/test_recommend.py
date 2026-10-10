import pytest

from services.recommend import (
    CheckpointRisk as CP,
    RouteInput,
    attribute_miles,
    compute_route_stats,
    recommend_route,
)
from services.risk import RiskLevel as L


def route(rid, total, dur_s, levels, spacing=None):
    """Build a route with checkpoints evenly spaced (default: total/(n-1), first at 0, last at total)."""
    n = len(levels)
    step = spacing if spacing is not None else (total / (n - 1) if n > 1 else 0)
    return RouteInput(rid, total, dur_s, tuple(CP(i * step, lvl) for i, lvl in enumerate(levels)))


# --- mile attribution -----------------------------------------------------
def test_attribution_sums_to_total():
    cps = tuple(CP(d, L.LOW) for d in (0, 10, 20, 30))
    owned = attribute_miles(cps, 30)
    assert owned == [5, 10, 10, 5]
    assert sum(owned) == 30


def test_attribution_when_last_checkpoint_short_of_end():
    cps = tuple(CP(d, L.LOW) for d in (0, 10, 20))
    owned = attribute_miles(cps, 25)  # last checkpoint owns through mile 25
    assert owned == [5, 10, 10] and sum(owned) == 25


def test_single_checkpoint_owns_whole_route():
    assert attribute_miles((CP(0, L.HIGH),), 42) == [42]


def test_unordered_checkpoints_rejected():
    with pytest.raises(ValueError):
        attribute_miles((CP(10, L.LOW), CP(5, L.LOW)), 20)


# --- stats ----------------------------------------------------------------
def test_stats_miles_and_average():
    r = route("A", 30, 3600, [L.LOW, L.HIGH, L.HIGH, L.SEVERE])  # owned 5,10,10,5
    s = compute_route_stats(r)
    assert s.miles_by_level[L.LOW] == 5
    assert s.high_miles == 20
    assert s.severe_miles == 5
    assert s.average_risk == pytest.approx((1 * 5 + 3 * 20 + 4 * 5) / 30)
    assert s.max_level == L.SEVERE and not s.blocked


def test_no_travel_marks_route_blocked():
    s = compute_route_stats(route("A", 20, 100, [L.LOW, L.NO_TRAVEL]))
    assert s.blocked and s.no_travel_miles == 10


# --- ranking: strict priority order --------------------------------------
def test_fewest_severe_miles_beats_everything_else():
    fast_but_severe = route("fast", 100, 3600, [L.LOW, L.SEVERE, L.LOW])
    slow_but_calm = route("slow", 100, 36000, [L.HIGH, L.HIGH, L.HIGH])
    rec = recommend_route([fast_but_severe, slow_but_calm])
    assert rec.best.stats.route_id == "slow"
    assert "Severe" in rec.summary


def test_high_miles_break_severe_tie():
    a = route("A", 100, 3600, [L.HIGH, L.HIGH, L.HIGH])
    b = route("B", 100, 7200, [L.MODERATE, L.HIGH, L.MODERATE])
    assert recommend_route([a, b]).best.stats.route_id == "B"


def test_average_risk_breaks_tie_on_severe_and_high():
    a = route("A", 100, 3600, [L.MODERATE, L.MODERATE, L.MODERATE])
    b = route("B", 100, 7200, [L.LOW, L.LOW, L.LOW])
    assert recommend_route([a, b]).best.stats.route_id == "B"


def test_travel_time_is_last_tiebreaker():
    a = route("A", 100, 7200, [L.LOW, L.LOW])
    b = route("B", 100, 3600, [L.LOW, L.LOW])
    rec = recommend_route([a, b])
    assert rec.best.stats.route_id == "B" and "travel time" in rec.summary


def test_no_travel_route_ranks_last_even_if_otherwise_better():
    blocked = route("blocked", 100, 1800, [L.LOW, L.NO_TRAVEL, L.LOW])
    severe = route("severe", 100, 9000, [L.SEVERE, L.SEVERE, L.SEVERE])
    rec = recommend_route([blocked, severe])
    assert [r.stats.route_id for r in rec.ranked] == ["severe", "blocked"]


def test_all_routes_blocked_picks_least_bad_and_warns():
    a = route("A", 100, 3600, [L.NO_TRAVEL, L.NO_TRAVEL, L.NO_TRAVEL])
    b = route("B", 100, 3600, [L.LOW, L.NO_TRAVEL, L.LOW])
    rec = recommend_route([a, b])
    assert rec.best.stats.route_id == "B"
    assert "No Travel" in rec.summary


def test_ranks_and_flags():
    rs = [route(x, 50, 100 * i, [L.LOW, L.LOW]) for i, x in enumerate("ABC", 1)]
    rec = recommend_route(rs)
    assert [r.rank for r in rec.ranked] == [1, 2, 3]
    assert [r.recommended for r in rec.ranked] == [True, False, False]


def test_full_tie_keeps_input_order():
    a, b = route("A", 50, 100, [L.LOW, L.LOW]), route("B", 50, 100, [L.LOW, L.LOW])
    assert recommend_route([a, b]).best.stats.route_id == "A"


def test_float_noise_does_not_decide_ranking():
    a = route("A", 100, 7200, [L.LOW, L.SEVERE, L.LOW])
    b = route("B", 100.000001, 3600, [L.LOW, L.SEVERE, L.LOW])  # same severe miles at 0.01 mi precision
    assert recommend_route([a, b]).best.stats.route_id == "B"


def test_single_route():
    rec = recommend_route([route("A", 10, 100, [L.LOW, L.LOW])])
    assert rec.best.recommended and "Only one" in rec.summary


def test_empty_inputs_rejected():
    with pytest.raises(ValueError):
        recommend_route([])
    with pytest.raises(ValueError):
        compute_route_stats(RouteInput("x", 10, 10, ()))

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.analysis import InvalidTrip, Location, analyze_trip
from services.routing import Route
from services.sampling import haversine_mi
from services.weather import WeatherSample

DEP = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
O, D = Location(0.0, 0.0, "Start"), Location(0.0, 3.0, "End")  # ~207 mi along the equator


def make_route(rid, lat, summary, speed_mps=25.0, points=60):
    """A west-east route bulging to `lat` in the middle."""
    coords = []
    for i in range(points + 1):
        f = i / points
        bulge = lat * (1 - abs(2 * f - 1))  # 0 at the ends, `lat` at the middle
        coords.append((bulge, 3.0 * f))
    dist_m = sum(haversine_mi(a, b) for a, b in zip(coords, coords[1:])) * 1609.344
    return Route(rid, tuple(coords), dist_m / 1609.344, dist_m / speed_mps, None, summary)


class FakeRouting:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get_routes(self, origin, destination):
        self.calls.append((origin, destination))
        return self.routes


class FakeWeather:
    """Wind depends on how far north a checkpoint is, so routes bulging north get worse weather."""

    wind_metric = "sustained"

    def __init__(self, wind_fn=None, rain=0.0, snow=0.0):
        self.wind_fn = wind_fn or (lambda lat, lon: 10.0)
        self.rain, self.snow = rain, snow
        self.calls = []

    def get_weather(self, requests, *, prefetch_points=(), prefetch_until=None):
        self.calls.append(list(requests))
        self.prefetch = (list(prefetch_points), prefetch_until)
        return [
            WeatherSample(when, self.wind_fn(lat, lon), self.wind_fn(lat, lon) + 8, self.rain, self.snow)
            for lat, lon, when in requests
        ]


def three_routes():
    return [
        make_route("route-1", 0.0, "Direct"),
        make_route("route-2", 0.8, "Northern"),
        make_route("route-3", -0.8, "Southern"),
    ]


def run(routing=None, weather=None, load_lb=20_000, departure=DEP):
    routing = routing or FakeRouting(three_routes())
    weather = weather or FakeWeather()
    return analyze_trip(O, D, departure, load_lb, routing=routing, weather=weather), routing, weather


# --- structure ---------------------------------------------------------------
def test_response_is_json_serializable_and_complete():
    out, _, _ = run()
    json.dumps(out)
    assert set(out) == {"request", "recommended_route_id", "recommendation", "routes", "corridor", "meta"}
    assert len(out["routes"]) == 3
    r = out["routes"][0]
    assert set(r) == {"id", "summary", "rank", "recommended", "distance_mi", "duration_s",
                      "arrival", "stats", "geometry", "checkpoints"}
    cp = r["checkpoints"][0]
    assert {"index", "distance_mi", "lat", "lon", "eta", "weather", "risk"} <= set(cp)
    assert {"wind_mph", "rain_in_hr", "snow_in_hr"} <= set(cp["weather"])
    assert {"level", "reason"} <= set(cp["risk"])
    assert out["request"]["load_lb"] == 20_000 and out["meta"]["wind_metric"] == "sustained"


def test_geometry_is_lon_lat_and_simplified():
    out, _, _ = run()
    geom = out["routes"][0]["geometry"]
    assert geom[0] == [0.0, 0.0] and geom[-1] == [3.0, 0.0]  # [lon, lat]
    assert len(geom) < 61


def test_checkpoints_start_at_origin_and_arrive_at_destination():
    out, _, _ = run()
    for r in out["routes"]:
        cps = r["checkpoints"]
        assert cps[0]["distance_mi"] == 0 and cps[0]["eta"] == DEP.isoformat()
        assert cps[-1]["distance_mi"] == pytest.approx(r["distance_mi"], abs=0.1)
        assert cps[-1]["eta"] == r["arrival"]


def test_routes_come_back_best_first_with_ranks():
    out, _, _ = run()
    assert [r["rank"] for r in out["routes"]] == [1, 2, 3]
    assert [r["recommended"] for r in out["routes"]] == [True, False, False]
    assert out["recommended_route_id"] == out["routes"][0]["id"]


# --- weather batching and timing -----------------------------------------------
def test_one_batched_weather_call_with_checkpoint_etas():
    out, _, weather = run()
    assert len(weather.calls) == 1
    total = sum(len(r["checkpoints"]) for r in out["routes"])
    assert len(weather.calls[0]) == total
    first_route = next(r for r in out["routes"] if r["id"] == "route-1")
    requested_times = {w for _, _, w in weather.calls[0]}
    assert datetime.fromisoformat(first_route["checkpoints"][3]["eta"]) in requested_times


def test_departure_is_normalised_to_utc():
    eat = timezone(timedelta(hours=3))
    out, _, _ = run(departure=datetime(2026, 10, 12, 11, 0, tzinfo=eat))
    assert out["request"]["departure"] == DEP.isoformat()
    assert out["routes"][0]["checkpoints"][0]["eta"] == DEP.isoformat()


# --- recommendation behaviour -----------------------------------------------------
def test_avoids_the_route_through_bad_weather():
    # Strong wind in the north: the northern bulge gets Severe/High stretches
    weather = FakeWeather(wind_fn=lambda lat, lon: 40.0 if lat > 0.3 else 10.0)
    out, _, _ = run(weather=weather)
    northern = next(r for r in out["routes"] if r["id"] == "route-2")
    assert out["recommended_route_id"] != "route-2"
    assert northern["rank"] == 3
    assert northern["stats"]["high_miles"] > 0


def test_load_weight_changes_the_outcome():
    # 50 mph wind in the north: Severe for a light load, No Travel for a heavy one
    wind = lambda lat, lon: 50.0 if lat > 0.3 else 10.0
    light, _, _ = run(weather=FakeWeather(wind_fn=wind), load_lb=25_000)
    heavy, _, _ = run(weather=FakeWeather(wind_fn=wind), load_lb=35_000)
    north = lambda out: next(r for r in out["routes"] if r["id"] == "route-2")
    assert north(light)["stats"]["severe_miles"] > 0 and not north(light)["stats"]["blocked"]
    assert north(heavy)["stats"]["blocked"] and north(heavy)["rank"] == 3
    reasons = {cp["risk"]["reason"] for cp in north(heavy)["checkpoints"]}
    assert any("35,000 lb" in r for r in reasons)


def test_all_routes_blocked_is_flagged():
    out, _, _ = run(weather=FakeWeather(wind_fn=lambda lat, lon: 60.0))
    assert all(r["stats"]["blocked"] for r in out["routes"])
    assert "No Travel" in out["recommendation"]["summary"]


def test_clear_weather_picks_fastest():
    out, _, _ = run()
    best = out["routes"][0]
    assert best["id"] == "route-1"  # shortest of the three, nothing else differs
    assert "travel time" in out["recommendation"]["summary"]


def test_single_route_still_works():
    out, _, _ = run(routing=FakeRouting([make_route("route-1", 0.0, "Only")]))
    assert len(out["routes"]) == 1 and out["routes"][0]["recommended"]


# --- validation -----------------------------------------------------------------
def test_same_origin_and_destination_rejected_before_any_api_call():
    routing, weather = FakeRouting(three_routes()), FakeWeather()
    with pytest.raises(InvalidTrip):
        analyze_trip(O, O, DEP, 10_000, routing=routing, weather=weather)
    assert routing.calls == [] and weather.calls == []


def test_naive_departure_and_negative_load_rejected():
    with pytest.raises(InvalidTrip):
        run(departure=datetime(2026, 10, 12, 8, 0))
    with pytest.raises(InvalidTrip):
        run(load_lb=-1)


def test_route_without_label_gets_default_summary():
    r = make_route("route-2", 0.1, "")
    out, _, _ = run(routing=FakeRouting([r]))
    assert out["routes"][0]["summary"] == "Route 2"


# --- corridor points for the heatmap ---------------------------------------------
def test_corridor_covers_all_routes_without_duplicates():
    from services.weather import grid_key

    out, _, _ = run()
    pts = out["corridor"]
    assert 20 < len(pts) < 400
    cells = [grid_key(p["lat"], p["lon"]) for p in pts]
    assert len(cells) == len(set(cells))  # one point per weather cell
    assert {"lat", "lon"} == set(pts[0])
    lats = [p["lat"] for p in pts]
    assert max(lats) > 0.3 and min(lats) < -0.3  # includes the northern and southern routes
    assert pts[0] == {"lat": 0.0, "lon": 0.0}  # starts at the origin


def test_weather_prefetch_covers_corridor_and_next_48_hours():
    out, _, weather = run()
    points, until = weather.prefetch
    assert until == DEP + timedelta(hours=48)
    assert [{"lat": lat, "lon": lon} for lat, lon in points] == out["corridor"]

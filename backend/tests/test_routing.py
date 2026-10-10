import pytest

from services.routing import (
    NoRouteFound,
    RoutingClient,
    RoutingError,
    RoutingUnavailable,
    distinct_share,
    parse_route,
    via_candidates,
)
from services.sampling import haversine_mi

O, D = (0.0, 0.0), (0.0, 3.0)  # along the equator, ~207 mi


def path(waypoints, per_leg=20):
    """Dense lon/lat polyline through (lat, lon) waypoints + the index where each leg ends."""
    pts, leg_ends = [(waypoints[0][1], waypoints[0][0])], []
    for (la1, lo1), (la2, lo2) in zip(waypoints, waypoints[1:]):
        for i in range(1, per_leg + 1):
            f = i / per_leg
            pts.append((lo1 + f * (lo2 - lo1), la1 + f * (la2 - la1)))
        leg_ends.append(len(pts) - 1)
    return pts, leg_ends


def raw_route(waypoints, speed_mps=25.0, summary="I-1"):
    pts, leg_ends = path(waypoints)
    seg_m = [haversine_mi((pts[i][1], pts[i][0]), (pts[i + 1][1], pts[i + 1][0])) * 1609.344 for i in range(len(pts) - 1)]
    legs, start = [], 0
    for end in leg_ends:
        legs.append({"summary": summary, "annotation": {"duration": [m / speed_mps for m in seg_m[start:end]]}})
        start = end
    return {
        "distance": sum(seg_m), "duration": sum(seg_m) / speed_mps,
        "geometry": {"coordinates": [list(p) for p in pts]}, "legs": legs,
    }


class FakeMapbox:
    def __init__(self, primary=None, detour=None, fail_times=0, code="Ok"):
        self.calls = []
        self.primary = primary if primary is not None else [raw_route([O, D])]
        self.detour = detour  # callable(waypoints) -> raw route, default builds path through via
        self.fail_times, self.code = fail_times, code

    def __call__(self, url, params):
        self.calls.append((url, params))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RoutingUnavailable("boom")
        if self.code != "Ok":
            return {"code": self.code, "message": "nope", "routes": []}
        wps = [tuple(map(float, c.split(",")))[::-1] for c in url.rsplit("/", 1)[1].split(";")]
        if len(wps) == 2:
            return {"code": "Ok", "routes": self.primary}
        return {"code": "Ok", "routes": [self.detour(wps) if self.detour else raw_route(wps)]}


def client(http, **kw):
    return RoutingClient("pk.test", http_get=http, sleep=lambda s: None, **kw)


# --- parsing ---------------------------------------------------------------
def test_parse_route_swaps_axes_and_converts_units():
    r = parse_route(raw_route([(1.0, 2.0), (1.0, 3.0)]))
    assert r.coords[0] == (1.0, 2.0) and r.coords[-1] == (1.0, 3.0)
    assert r.distance_mi == pytest.approx(haversine_mi((1, 2), (1, 3)), rel=1e-6)
    assert len(r.segment_durations_s) == len(r.coords) - 1
    assert r.summary == "I-1"
    assert r.geojson_coords()[0] == [2.0, 1.0]


def test_parse_route_joins_leg_annotations():
    r = parse_route(raw_route([O, (0.5, 1.0), D]))  # two legs
    assert len(r.segment_durations_s) == len(r.coords) - 1


def test_parse_route_without_annotations_has_none():
    raw = raw_route([O, D])
    raw["legs"] = [{"summary": "x"}]
    assert parse_route(raw).segment_durations_s is None


def test_parse_route_mismatched_annotations_dropped():
    raw = raw_route([O, D])
    raw["legs"][0]["annotation"]["duration"].pop()
    assert parse_route(raw).segment_durations_s is None


def test_parse_route_malformed():
    with pytest.raises(RoutingUnavailable):
        parse_route({"distance": 1})


# --- requests ---------------------------------------------------------------
def test_request_format():
    http = FakeMapbox(primary=[raw_route([O, D])] * 3)
    client(http).get_routes((10.5, 20.25), (11.5, 21.0))
    url, params = http.calls[0]
    assert url.endswith("/mapbox/driving/20.250000,10.500000;21.000000,11.500000")
    assert params["alternatives"] == "true" and params["overview"] == "full"
    assert params["geometries"] == "geojson" and params["annotations"] == "duration"
    assert params["access_token"] == "pk.test"


def test_three_routes_from_api_need_no_detours():
    http = FakeMapbox(primary=[raw_route([O, D]), raw_route([O, (0.3, 1.5), D]), raw_route([O, (-0.3, 1.5), D])])
    routes = client(http).get_routes(O, D)
    assert [r.route_id for r in routes] == ["route-1", "route-2", "route-3"]
    assert len(http.calls) == 1


def test_extra_api_routes_are_capped_at_three():
    http = FakeMapbox(primary=[raw_route([O, D])] * 4)
    assert len(client(http).get_routes(O, D)) == 3


# --- detour fallback -----------------------------------------------------------
def test_fills_up_to_three_routes_with_distinct_detours():
    http = FakeMapbox()  # API returns only the straight route
    routes = client(http).get_routes(O, D)
    assert len(routes) == 3
    assert len(http.calls) == 3  # primary + 2 detours, then stops
    assert all(len(url.rsplit("/", 1)[1].split(";")) == 3 for url, _ in http.calls[1:])
    assert distinct_share(routes[1], [routes[0]]) >= 0.2
    assert distinct_share(routes[2], routes[:2]) >= 0.2


def test_detours_that_duplicate_existing_route_are_rejected():
    http = FakeMapbox(detour=lambda wps: raw_route([O, D]))  # "detour" is the same road
    routes = client(http).get_routes(O, D)
    assert len(routes) == 1
    assert len(http.calls) == 1 + 4  # primary + both offsets for both fractions


def test_absurdly_long_detours_are_rejected():
    http = FakeMapbox(detour=lambda wps: raw_route(wps, speed_mps=2.0))  # ~12x slower
    assert len(client(http).get_routes(O, D)) == 1


def test_failed_detour_requests_do_not_break_result():
    class Flaky(FakeMapbox):
        def __call__(self, url, params):
            if len(url.rsplit("/", 1)[1].split(";")) == 3:
                raise RoutingUnavailable("down")
            return super().__call__(url, params)

    routes = client(Flaky()).get_routes(O, D)
    assert len(routes) == 1


def test_via_candidates_are_perpendicular_and_symmetric():
    left, right = via_candidates(O, D, 40)
    mid = (0.0, 1.5)
    assert haversine_mi(mid, left) == pytest.approx(40, rel=0.02)
    assert haversine_mi(mid, right) == pytest.approx(40, rel=0.02)
    assert left[0] == pytest.approx(-right[0]) and left[1] == pytest.approx(1.5, abs=1e-6)


def test_via_candidates_same_point():
    with pytest.raises(ValueError):
        via_candidates(O, O, 10)


# --- errors -----------------------------------------------------------------
def test_no_route():
    with pytest.raises(NoRouteFound):
        client(FakeMapbox(code="NoRoute")).get_routes(O, D)


def test_empty_routes_list():
    with pytest.raises(NoRouteFound):
        client(FakeMapbox(primary=[])).get_routes(O, D)


def test_retries_then_succeeds_and_gives_up():
    http = FakeMapbox(fail_times=2, primary=[raw_route([O, D])] * 3)
    assert len(client(http).get_routes(O, D)) == 3 and len(http.calls) == 3
    with pytest.raises(RoutingUnavailable):
        client(FakeMapbox(fail_times=9)).get_routes(O, D)


def test_missing_token_and_same_place():
    with pytest.raises(RoutingError):
        RoutingClient("")
    with pytest.raises(ValueError):
        client(FakeMapbox()).get_routes(O, O)

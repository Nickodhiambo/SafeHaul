from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from api import deps
from services.geocoding import GeocodingUnavailable, Place, PlaceNotFound
from services.routing import NoRouteFound, RoutingError, RoutingUnavailable
from services.weather import ForecastRangeError, WeatherUnavailable

from .test_analysis import FakeRouting, FakeWeather, three_routes

ORIGIN = {"lat": 0.0, "lon": 0.0, "label": "Start"}
DEST = {"lat": 0.0, "lon": 3.0, "label": "End"}


def departure(hours=2):
    return (timezone.now() + timedelta(hours=hours)).isoformat()


def body(**over):
    b = {"origin": ORIGIN, "destination": DEST, "departure": departure(), "load_lb": 30000}
    b.update(over)
    return b


class FakeGeocoder:
    def __init__(self, places=None, error=None):
        self.places = places if places is not None else [Place("1", "Dallas", "Dallas, Texas, United States", 32.78, -96.8, "place")]
        self.error, self.queries = error, []

    def search(self, q, proximity=None, **_):
        self.queries.append((q, proximity))
        if self.error:
            raise self.error
        if len(q.strip()) < 2:
            return []
        if len(q) > 256:
            raise ValueError("query is longer than 256 characters")
        return self.places

    def resolve(self, q):
        if self.error:
            raise self.error
        if not self.places:
            raise PlaceNotFound(f"Couldn't find a place matching '{q}'")
        return self.places[0]


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()


@pytest.fixture
def services(monkeypatch):
    s = SimpleNamespace(routing=FakeRouting(three_routes()), weather=FakeWeather(), geocoding=FakeGeocoder())
    monkeypatch.setattr(deps, "get_services", lambda: s)
    return s


@pytest.fixture
def api():
    return APIClient()


def post(api, payload):
    return api.post("/api/analyze/", payload, format="json")


# --- health / geocode -----------------------------------------------------------
def test_health(api):
    assert api.get("/api/health/").json() == {"status": "ok"}


def test_geocode_returns_results(api, services):
    r = api.get("/api/geocode/", {"q": "Dall", "lat": "30.5", "lon": "-97.0"})
    assert r.status_code == 200
    assert r.json()["results"][0]["label"].startswith("Dallas")
    assert services.geocoding.queries == [("Dall", (30.5, -97.0))]


def test_geocode_short_query_is_empty(api, services):
    assert api.get("/api/geocode/", {"q": "D"}).json() == {"results": []}
    assert api.get("/api/geocode/").json() == {"results": []}


def test_geocode_bad_proximity_and_long_query(api, services):
    assert api.get("/api/geocode/", {"q": "Dallas", "lat": "x", "lon": "1"}).status_code == 400
    assert api.get("/api/geocode/", {"q": "x" * 300}).status_code == 400


def test_geocode_upstream_down(api, services):
    services.geocoding.error = GeocodingUnavailable("down")
    r = api.get("/api/geocode/", {"q": "Dallas"})
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_unavailable"


# --- analyze: success ---------------------------------------------------------------
def test_analyze_success(api, services):
    r = post(api, body())
    assert r.status_code == 200
    data = r.json()
    assert len(data["routes"]) == 3 and data["recommended_route_id"]
    assert data["routes"][0]["recommended"] is True
    assert data["request"]["origin"]["label"] == "Start"


def test_analyze_passes_coordinates_and_load_through(api, services):
    post(api, body(load_lb=41000))
    assert services.routing.calls == [((0.0, 0.0), (0.0, 3.0))]


def test_analyze_geocodes_typed_places(api, services):
    r = post(api, body(origin={"query": "Dallas, TX"}))
    assert r.status_code == 200
    assert r.json()["request"]["origin"]["label"] == "Dallas, Texas, United States"
    assert services.routing.calls[0][0] == (32.78, -96.8)


def test_departure_with_offset_is_accepted_and_converted_to_utc(api, services):
    dep = (timezone.now() + timedelta(hours=3)).astimezone(timezone.get_fixed_timezone(180)).isoformat()
    r = post(api, body(departure=dep))
    assert r.status_code == 200 and r.json()["request"]["departure"].endswith("+00:00")


def test_recent_past_departure_within_grace_is_allowed(api, services):
    assert post(api, body(departure=departure(hours=-0.5))).status_code == 200


# --- analyze: validation ----------------------------------------------------------------
@pytest.mark.parametrize("override,field", [
    ({"departure": "2026-10-12T08:00:00"}, "departure"),  # naive
    ({"departure": "tomorrow"}, "departure"),
    ({"departure": "2020-01-01T08:00:00Z"}, "departure"),  # past
    ({"load_lb": -5}, "load_lb"),
    ({"load_lb": 1_000_000}, "load_lb"),
    ({"load_lb": "heavy"}, "load_lb"),
    ({"origin": {"lat": 95, "lon": 0}}, "origin"),
    ({"origin": {"lat": 10}}, "origin"),
    ({"origin": {}}, "origin"),
    ({"destination": {"query": "   "}}, "destination"),
])
def test_invalid_requests_rejected_with_field_errors(api, services, override, field):
    r = post(api, body(**override))
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == "invalid_request" and field in err["fields"]


def test_missing_fields(api, services):
    r = post(api, {})
    assert r.status_code == 400
    assert {"origin", "destination", "departure", "load_lb"} <= set(r.json()["error"]["fields"])


def test_same_origin_and_destination(api, services):
    r = post(api, body(destination=ORIGIN))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_trip"


# --- analyze: upstream failures ------------------------------------------------------------
@pytest.mark.parametrize("raiser,status,code", [
    (("routing", NoRouteFound("No drivable route found")), 404, "no_route"),
    (("routing", RoutingUnavailable("x")), 502, "upstream_unavailable"),
    (("routing", RoutingError("token")), 502, "upstream_error"),
    (("weather", WeatherUnavailable("x")), 502, "upstream_unavailable"),
    (("weather", ForecastRangeError("x")), 422, "forecast_unavailable"),
    (("geocoding", PlaceNotFound("Couldn't find a place matching 'zz'")), 404, "place_not_found"),
    (("geocoding", GeocodingUnavailable("x")), 502, "upstream_unavailable"),
])
def test_upstream_errors_map_to_clean_responses(api, services, raiser, status, code):
    which, exc = raiser

    def boom(*a, **k):
        raise exc

    target = {"routing": "get_routes", "weather": "get_weather", "geocoding": "resolve"}[which]
    setattr(getattr(services, which), target, boom)
    payload = body(origin={"query": "zz"}) if which == "geocoding" else body()
    r = post(api, payload)
    assert r.status_code == status and r.json()["error"]["code"] == code
    assert "Traceback" not in r.content.decode()


def test_missing_token_configuration_is_a_clean_error(api, monkeypatch):
    def broken():
        raise RoutingError("MAPBOX_TOKEN is not configured")

    monkeypatch.setattr(deps, "get_services", broken)
    r = post(api, body())
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_error"


def test_only_post_allowed_on_analyze(api, services):
    assert api.get("/api/analyze/").status_code == 405


# --- heatmap ---------------------------------------------------------------------------
from services.weather import WeatherClient  # noqa: E402


class LiveClockHttp:
    """Open-Meteo stand-in whose series starts at today's 00:00 GMT (matches the real clock)."""

    def __init__(self, error=None):
        self.error, self.calls = error, []

    def __call__(self, url, params):
        self.calls.append(params)
        if self.error:
            raise self.error
        midnight = int(timezone.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        n = params["forecast_days"] * 24
        out = []
        for la, lo in zip(params["latitude"].split(","), params["longitude"].split(",")):
            out.append({"hourly": {
                "time": [midnight + 3600 * i for i in range(n)],
                "wind_speed_10m": [12.0] * n, "wind_gusts_10m": [20.0] * n,
                "rain": [0.0] * n, "showers": [0.0] * n, "snowfall": [0.0] * n,
            }})
        return out if len(out) > 1 else out[0]


@pytest.fixture
def heat_services(monkeypatch):
    http = LiveClockHttp()
    weather = WeatherClient(http_get=http, sleep=lambda s: None)
    s = SimpleNamespace(routing=None, weather=weather, geocoding=None, http=http)
    monkeypatch.setattr(deps, "get_services", lambda: s)
    return s


def heat_body(**over):
    b = {"points": [{"lat": 36.8, "lon": -1.3}, {"lat": 41.9, "lon": -87.6}],
         "start": departure(), "load_lb": 30000}
    b.update(over)
    return b


def post_heat(api, payload):
    return api.post("/api/heatmap/", payload, format="json")


def test_heatmap_success(api, heat_services):
    r = post_heat(api, heat_body())
    assert r.status_code == 200
    d = r.json()
    assert d["hours"] == 48 and len(d["points"]) == 2
    assert len(d["points"][0]["level"]) == 49 and set(d["points"][0]["level"]) == {1}  # calm weather
    assert len(heat_services.http.calls) == 1  # both points in one batched request


def test_heatmap_hours_option(api, heat_services):
    d = post_heat(api, heat_body(hours=12)).json()
    assert d["hours"] == 12 and len(d["points"][0]["level"]) == 13


@pytest.mark.parametrize("override,field", [
    ({"points": []}, "points"),
    ({"points": [{"lat": 1}]}, "points"),
    ({"points": [{"lat": 99, "lon": 0}]}, "points"),
    ({"points": [{"lat": 1.0, "lon": 1.0}] * 401}, "points"),
    ({"start": "2026-10-12T08:00:00"}, "start"),
    ({"start": "2020-01-01T08:00:00Z"}, "start"),
    ({"hours": 0}, "hours"),
    ({"hours": 49}, "hours"),
    ({"load_lb": -1}, "load_lb"),
])
def test_heatmap_validation(api, heat_services, override, field):
    r = post_heat(api, heat_body(**override))
    assert r.status_code == 400 and field in r.json()["error"]["fields"]


def test_heatmap_start_beyond_forecast_window(api, heat_services):
    r = post_heat(api, heat_body(start=departure(hours=24 * 20)))
    assert r.status_code == 422 and r.json()["error"]["code"] == "forecast_unavailable"


def test_heatmap_weather_provider_down(api, monkeypatch):
    http = LiveClockHttp(error=WeatherUnavailable("down"))
    s = SimpleNamespace(weather=WeatherClient(http_get=http, sleep=lambda s: None))
    monkeypatch.setattr(deps, "get_services", lambda: s)
    r = post_heat(api, heat_body())
    assert r.status_code == 502 and r.json()["error"]["code"] == "upstream_unavailable"


def test_analyze_response_corridor_feeds_the_heatmap_request(api, services, monkeypatch):
    corridor = post(api, body()).json()["corridor"]
    assert corridor and {"lat", "lon"} == set(corridor[0])

    heat = SimpleNamespace(weather=WeatherClient(http_get=LiveClockHttp(), sleep=lambda s: None))
    monkeypatch.setattr(deps, "get_services", lambda: heat)  # swap in the heatmap's weather client
    r = post_heat(api, heat_body(points=corridor[:5]))
    assert r.status_code == 200 and len(r.json()["points"]) == 5


def test_heatmap_after_analyze_makes_no_weather_provider_calls(api, monkeypatch):
    http = LiveClockHttp()
    s = SimpleNamespace(
        routing=FakeRouting(three_routes()),
        weather=WeatherClient(http_get=http, sleep=lambda s: None),
        geocoding=FakeGeocoder(),
    )
    monkeypatch.setattr(deps, "get_services", lambda: s)

    analysis = post(api, body()).json()
    calls_after_analyze = len(http.calls)
    assert calls_after_analyze >= 1

    r = post_heat(api, {
        "points": analysis["corridor"],
        "start": analysis["request"]["departure"],
        "load_lb": 30000,
    })
    assert r.status_code == 200 and r.json()["hours"] == 48
    assert len(http.calls) == calls_after_analyze  # served entirely from the warmed cache

import pytest

from services.geocoding import (
    GeocodingClient,
    GeocodingError,
    GeocodingUnavailable,
    PlaceNotFound,
    parse_features,
)


def feature(name="Chicago", full="Chicago, Illinois, United States", lon=-87.63, lat=41.88,
            ftype="place", mid="dXJuOm1ieHBsYzox"):
    return {
        "type": "Feature",
        "id": mid,
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": {"mapbox_id": mid, "feature_type": ftype, "name": name, "full_address": full,
                       "place_formatted": "Illinois, United States"},
    }


class FakeHttp:
    def __init__(self, features=None, fail_times=0):
        self.calls = []
        self.features = [feature()] if features is None else features
        self.fail_times = fail_times

    def __call__(self, url, params):
        self.calls.append((url, params))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise GeocodingUnavailable("boom")
        return {"type": "FeatureCollection", "features": self.features}


def client(http, **kw):
    return GeocodingClient("pk.test", http_get=http, sleep=lambda s: None, **kw)


def test_parse_swaps_axes_and_reads_fields():
    [p] = parse_features({"features": [feature()]})
    assert (p.lat, p.lon) == (41.88, -87.63)
    assert p.name == "Chicago" and p.label == "Chicago, Illinois, United States"
    assert p.feature_type == "place" and p.id == "dXJuOm1ieHBsYzox"
    assert p.to_dict()["lat"] == 41.88


def test_parse_skips_countries_and_malformed_features():
    feats = [feature(ftype="country", name="United States"), {"properties": {}}, {"geometry": {}}, feature()]
    assert [p.name for p in parse_features({"features": feats})] == ["Chicago"]


def test_parse_builds_label_when_full_address_missing():
    f = feature()
    del f["properties"]["full_address"]
    assert parse_features({"features": [f]})[0].label == "Chicago, Illinois, United States"


def test_parse_bad_payload():
    with pytest.raises(GeocodingUnavailable):
        parse_features([])
    assert parse_features({}) == []


def test_search_request_params():
    http = FakeHttp()
    client(http, country="us,ca").search("  Chicago ", limit=50, proximity=(41.0, -87.0))
    url, p = http.calls[0]
    assert url.endswith("/search/geocode/v6/forward")
    assert p["q"] == "Chicago" and p["limit"] == 10 and p["autocomplete"] == "true"
    assert p["country"] == "us,ca" and p["proximity"] == "-87.00000,41.00000"
    assert p["access_token"] == "pk.test" and "types" not in p


def test_optional_params_omitted_by_default():
    http = FakeHttp()
    client(http).search("Chicago")
    assert set(http.calls[0][1]) == {"q", "limit", "autocomplete", "access_token"}


def test_short_or_empty_queries_make_no_request():
    http = FakeHttp()
    c = client(http)
    assert c.search("") == [] and c.search("  ") == [] and c.search("a") == [] and c.search(None) == []
    assert http.calls == []


def test_overlong_query_rejected():
    with pytest.raises(ValueError):
        client(FakeHttp()).search("x" * 257)


def test_resolve_returns_first_match():
    http = FakeHttp([feature(ftype="country", name="US"), feature(), feature(name="Chicago Heights")])
    assert client(http).resolve("Chicago").name == "Chicago"
    assert http.calls[0][1]["limit"] == 3


def test_resolve_not_found_and_empty():
    with pytest.raises(PlaceNotFound):
        client(FakeHttp([])).resolve("Zzzzzz")
    with pytest.raises(ValueError):
        client(FakeHttp()).resolve("  ")


def test_retries_once_then_gives_up():
    ok = FakeHttp(fail_times=1)
    assert len(client(ok).search("Chicago")) == 1 and len(ok.calls) == 2
    with pytest.raises(GeocodingUnavailable):
        client(FakeHttp(fail_times=5)).search("Chicago")


def test_missing_token():
    with pytest.raises(GeocodingError):
        GeocodingClient("")

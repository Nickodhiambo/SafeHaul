from datetime import datetime, timedelta, timezone

import pytest

from services.weather import (
    ForecastRangeError,
    TTLCache,
    WeatherClient,
    WeatherUnavailable,
    grid_key,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 9, 30, tzinfo=UTC)
START = int(datetime(2026, 10, 10, 0, 0, tzinfo=UTC).timestamp())


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


class FakeHttp:
    """Hourly series from today 00:00 GMT. wind = hour index, gust = index + 10."""

    def __init__(self, fail_times=0, null_wind=False):
        self.calls = []
        self.fail_times = fail_times
        self.null_wind = null_wind

    def __call__(self, url, params):
        self.calls.append(params)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise WeatherUnavailable("boom")
        lats, lons = params["latitude"].split(","), params["longitude"].split(",")
        n = params["forecast_days"] * 24
        out = []
        for la, lo in zip(lats, lons):
            out.append({
                "latitude": float(la), "longitude": float(lo),
                "hourly": {
                    "time": [START + 3600 * i for i in range(n)],
                    "wind_speed_10m": [None if self.null_wind else float(i) for i in range(n)],
                    "wind_gusts_10m": [i + 10.0 for i in range(n)],
                    "rain": [0.10] * n,
                    "showers": [0.05] * n,
                    "snowfall": [0.2] * n,
                },
            })
        return out if len(out) > 1 else out[0]  # Open-Meteo: dict for one point, list for many


def make(http=None, **kw):
    http = http or FakeHttp()
    sleeps = []
    client = WeatherClient(http_get=http, now=lambda: NOW, sleep=sleeps.append, **kw)
    return client, http, sleeps


def test_single_point_values_units_and_request_params():
    client, http, _ = make()
    [s] = client.get_weather([(36.82, -1.29, at(10, 14))])
    assert (s.wind_mph, s.gust_mph) == (14.0, 24.0)
    assert s.rain_in_hr == pytest.approx(0.15)  # rain + showers
    assert s.snow_in_hr == pytest.approx(0.2)
    assert s.time == at(10, 14)
    p = http.calls[0]
    assert p["wind_speed_unit"] == "mph" and p["precipitation_unit"] == "inch"
    assert p["timeformat"] == "unixtime" and p["forecast_days"] == 1
    assert p["latitude"] == "36.8" and p["longitude"] == "-1.3"


def test_nearest_forecast_hour():
    client, _, _ = make()
    a, b = client.get_weather([(1, 1, at(10, 14, 29)), (1, 1, at(10, 14, 30))])
    assert a.wind_mph == 14 and b.wind_mph == 15


def test_forecast_days_follow_latest_time_needed():
    client, http, _ = make()
    client.get_weather([(1, 1, at(10, 12)), (1, 1, at(11, 20))])
    assert http.calls[0]["forecast_days"] == 2


def test_results_keep_request_order():
    client, _, _ = make()
    out = client.get_weather([(1, 1, at(10, 20)), (2, 2, at(10, 5)), (1, 1, at(10, 12))])
    assert [s.wind_mph for s in out] == [20, 5, 12]


def test_batches_of_50_and_order_preserved():
    client, http, _ = make()
    reqs = [(i * 0.1, 0.0, at(10, 12)) for i in range(120)]
    out = client.get_weather(reqs)
    assert len(out) == 120
    assert sorted(len(c["latitude"].split(",")) for c in http.calls) == [20, 50, 50]


def test_nearby_points_share_one_fetch():
    client, http, _ = make()
    client.get_weather([(36.81, -1.29, at(10, 12)), (36.84, -1.31, at(10, 13))])
    assert len(http.calls) == 1 and "," not in http.calls[0]["latitude"]
    assert grid_key(36.81, -1.29) == grid_key(36.84, -1.31)


def test_second_call_is_served_from_cache():
    client, http, _ = make()
    client.get_weather([(1, 1, at(10, 12))])
    client.get_weather([(1, 1, at(10, 18))])
    assert len(http.calls) == 1


def test_cache_refetches_when_window_too_short():
    client, http, _ = make()
    client.get_weather([(1, 1, at(10, 12))])  # 1 day
    client.get_weather([(1, 1, at(11, 12))])  # needs 2 days
    assert len(http.calls) == 2 and http.calls[1]["forecast_days"] == 2


def test_cache_expires():
    t = [0.0]
    client, http, _ = make(cache=TTLCache(clock=lambda: t[0]), ttl_s=100)
    client.get_weather([(1, 1, at(10, 12))])
    t[0] = 99
    client.get_weather([(1, 1, at(10, 12))])
    assert len(http.calls) == 1
    t[0] = 101
    client.get_weather([(1, 1, at(10, 12))])
    assert len(http.calls) == 2


def test_gust_metric():
    client, _, _ = make(wind_metric="gust")
    [s] = client.get_weather([(1, 1, at(10, 14))])
    assert s.wind_mph == 24.0 and s.gust_mph == 24.0
    with pytest.raises(ValueError):
        WeatherClient(wind_metric="nope")


def test_null_values_are_zero():
    client, _, _ = make(FakeHttp(null_wind=True))
    [s] = client.get_weather([(1, 1, at(10, 14))])
    assert s.wind_mph == 0.0


def test_retries_then_succeeds():
    client, http, sleeps = make(FakeHttp(fail_times=2))
    client.get_weather([(1, 1, at(10, 12))])
    assert len(http.calls) == 3 and sleeps == [0.5, 1.0]


def test_gives_up_after_retries():
    client, http, _ = make(FakeHttp(fail_times=5))
    with pytest.raises(WeatherUnavailable):
        client.get_weather([(1, 1, at(10, 12))])
    assert len(http.calls) == 3


def test_beyond_16_days_rejected():
    client, http, _ = make()
    with pytest.raises(ForecastRangeError):
        client.get_weather([(1, 1, NOW + timedelta(days=17))])
    assert http.calls == []


def test_time_in_the_past_rejected():
    client, _, _ = make()
    with pytest.raises(ForecastRangeError):
        client.get_weather([(1, 1, NOW - timedelta(days=2))])


def test_naive_time_rejected():
    client, _, _ = make()
    with pytest.raises(ValueError):
        client.get_weather([(1, 1, datetime(2026, 10, 10, 12))])


def test_empty_request():
    client, http, _ = make()
    assert client.get_weather([]) == [] and http.calls == []


def test_mismatched_response_rejected():
    def bad(url, params):
        return []
    client = WeatherClient(http_get=bad, now=lambda: NOW, sleep=lambda s: None)
    with pytest.raises(WeatherUnavailable):
        client.get_weather([(1, 1, at(10, 12))])


def test_malformed_series_rejected():
    def bad(url, params):
        return {"hourly": {"time": [START]}}
    client = WeatherClient(http_get=bad, now=lambda: NOW, sleep=lambda s: None)
    with pytest.raises(WeatherUnavailable):
        client.get_weather([(1, 1, at(10, 12))])

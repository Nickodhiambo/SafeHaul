from datetime import datetime, timedelta, timezone

import pytest

from services.heatmap import MAX_POINTS, build_heatmap
from services.weather import ForecastRangeError

from .test_weather import NOW, UTC, FakeHttp, at, make

# FakeHttp: wind = hour index since 2026-10-10 00:00 GMT, gust = wind + 10,
# rain = 0.15 in/hr (Moderate), snow = 0.2 in/hr (Low)
START = at(10, 10)  # wind at hour h after START = 10 + h
PT = [(36.8, -1.3)]


def heat(points=PT, start=START, load_lb=20_000, hours=48, **kw):
    client, http, _ = make(**kw)
    return build_heatmap(points, start, load_lb, weather=client, hours=hours), http


def test_shape_and_frame_count():
    out, _ = heat()
    assert out["hours"] == 48 and out["step_hours"] == 1
    p = out["points"][0]
    assert (p["lat"], p["lon"]) == (36.8, -1.3)
    for key in ("level", "wind_mph", "rain_in_hr", "snow_in_hr"):
        assert len(p[key]) == 49
    assert out["start"] == START.isoformat()
    assert out["legend"] == {"1": "Low", "2": "Moderate", "3": "High", "4": "Severe", "5": "No Travel"}


def test_levels_follow_the_forecast_hour_by_hour():
    p = heat()[0]["points"][0]
    assert p["wind_mph"][0] == 10 and p["wind_mph"][20] == 30
    assert p["level"][0] == 2  # rain 0.15 -> Moderate, wind 10 -> Low
    assert p["level"][24] == 2 and p["level"][25] == 3  # wind 35 -> High
    assert p["level"][34] == 3 and p["level"][35] == 4  # wind 45 -> Severe
    assert p["level"][44] == 4 and p["level"][45] == 5  # wind 55 -> No Travel
    assert p["rain_in_hr"][0] == pytest.approx(0.15) and p["snow_in_hr"][0] == pytest.approx(0.2)


def test_load_rules_apply_in_the_heatmap_too():
    heavy = heat(load_lb=35_000)[0]["points"][0]["level"]
    assert heavy[35] == 5  # 45 mph + >30,000 lb -> No Travel (a 20,000 lb load gives 4)
    very_heavy = heat(load_lb=45_000)[0]["points"][0]["level"]
    assert very_heavy[25] == 4  # 35 mph + >40,000 lb -> Severe (a 20,000 lb load gives 3)


def test_gust_metric_is_used_when_configured():
    p = heat(wind_metric="gust")[0]["points"][0]
    assert p["wind_mph"][0] == 20  # gust = wind + 10


def test_many_points_one_batched_request_and_order_kept():
    pts = [(i * 0.1, 0.0) for i in range(120)]
    out, http = heat(points=pts)
    assert [p["lat"] for p in out["points"]] == [round(x, 4) for x, _ in pts]
    assert sorted(len(c["latitude"].split(",")) for c in http.calls) == [20, 50, 50]


def test_points_in_the_same_weather_cell_share_one_fetch():
    out, http = heat(points=[(36.81, -1.29), (36.84, -1.31)])
    assert len(out["points"]) == 2 and len(http.calls) == 1 and "," not in http.calls[0]["latitude"]


def test_window_is_shortened_near_the_forecast_horizon():
    out, _ = heat(start=datetime(2026, 10, 25, 0, 0, tzinfo=UTC))  # window ends 2026-10-25 23:00
    assert out["hours"] == 23 and len(out["points"][0]["level"]) == 24


def test_start_beyond_the_horizon_is_an_error():
    with pytest.raises(ForecastRangeError):
        heat(start=datetime(2026, 10, 26, 0, 0, tzinfo=UTC))


def test_hours_parameter_limits_frames():
    out, _ = heat(hours=6)
    assert out["hours"] == 6 and len(out["points"][0]["level"]) == 7


def test_start_time_with_offset_is_normalised():
    eat = timezone(timedelta(hours=3))
    out, _ = heat(start=datetime(2026, 10, 10, 13, 0, tzinfo=eat))
    assert out["start"] == START.isoformat()


@pytest.mark.parametrize("kwargs", [
    {"points": []},
    {"points": [(0.0, 0.0)] * (MAX_POINTS + 1)},
    {"hours": 0},
    {"hours": 49},
    {"start": datetime(2026, 10, 10, 10, 0)},  # naive
])
def test_invalid_arguments(kwargs):
    with pytest.raises(ValueError):
        heat(**kwargs)

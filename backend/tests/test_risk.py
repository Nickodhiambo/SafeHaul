import pytest

from services.risk import (
    RiskLevel as L,
    apply_load_rules,
    assess_checkpoint,
    classify_rain,
    classify_snow,
    classify_wind,
)


@pytest.mark.parametrize("mph,expected", [
    (0, L.LOW), (24.9, L.LOW),
    (25, L.MODERATE), (34, L.MODERATE), (34.9, L.MODERATE),
    (35, L.HIGH), (44, L.HIGH), (44.9, L.HIGH),
    (45, L.SEVERE), (54, L.SEVERE), (54.9, L.SEVERE),
    (55, L.NO_TRAVEL), (80, L.NO_TRAVEL),
])
def test_wind_bands(mph, expected):
    assert classify_wind(mph) == expected


@pytest.mark.parametrize("rate,expected", [
    (0, L.LOW), (0.09, L.LOW),
    (0.10, L.MODERATE), (0.25, L.MODERATE),
    (0.26, L.HIGH), (0.50, L.HIGH),
    (0.51, L.SEVERE), (1.00, L.SEVERE),
    (1.01, L.NO_TRAVEL),
])
def test_rain_bands(rate, expected):
    assert classify_rain(rate) == expected


@pytest.mark.parametrize("rate,expected", [
    (0, L.LOW), (0.49, L.LOW),
    (0.5, L.MODERATE), (1.0, L.MODERATE),
    (1.01, L.HIGH), (2.0, L.HIGH),
    (2.01, L.SEVERE), (3.0, L.SEVERE),
    (3.01, L.NO_TRAVEL),
])
def test_snow_bands(rate, expected):
    assert classify_snow(rate) == expected


# --- load rules -----------------------------------------------------------
@pytest.mark.parametrize("load", [0, 10_000, 80_000])
def test_wind_55_is_no_travel_for_any_load(load):
    assert assess_checkpoint(55, 0, 0, load).level == L.NO_TRAVEL


def test_45_54_wind_heavy_load_is_no_travel():
    a = assess_checkpoint(50, 0, 0, 30_001)
    assert a.level == L.NO_TRAVEL and a.load_adjusted and a.driver == "load"


def test_45_54_wind_load_exactly_30000_stays_severe():
    a = assess_checkpoint(50, 0, 0, 30_000)  # rule is strictly > 30,000
    assert a.level == L.SEVERE and not a.load_adjusted


def test_35_44_wind_very_heavy_load_is_severe():
    a = assess_checkpoint(40, 0, 0, 40_001)
    assert a.level == L.SEVERE and a.load_adjusted


def test_35_44_wind_load_exactly_40000_stays_high():
    assert assess_checkpoint(40, 0, 0, 40_000).level == L.HIGH


def test_load_rule_does_not_lower_a_worse_weather_level():
    # Wind says Severe-via-load, but heavy snow already says No Travel
    a = assess_checkpoint(40, 0, 3.5, 45_000)
    assert a.level == L.NO_TRAVEL and not a.load_adjusted and a.driver == "snow"


def test_load_rule_does_not_apply_below_35_mph():
    assert assess_checkpoint(30, 0, 0, 80_000).level == L.MODERATE


def test_apply_load_rules_never_lowers():
    assert apply_load_rules(L.NO_TRAVEL, 40, 50_000) == L.NO_TRAVEL


# --- combining conditions -------------------------------------------------
def test_overall_is_worst_condition():
    a = assess_checkpoint(10, 0.3, 0.6, 20_000)  # low / high / moderate
    assert (a.wind_level, a.rain_level, a.snow_level) == (L.LOW, L.HIGH, L.MODERATE)
    assert a.level == L.HIGH and a.driver == "rain"


def test_all_clear():
    a = assess_checkpoint(5, 0, 0, 40_000)
    assert a.level == L.LOW and a.driver == "none"


def test_reason_strings():
    assert assess_checkpoint(47, 0, 0, 35_000).reason == "Wind 47 mph with a 35,000 lb load → No Travel"
    assert assess_checkpoint(0, 0.3, 0, 1).reason == "Rain 0.3 in/hr → High"


@pytest.mark.parametrize("args", [(-1, 0, 0, 1), (0, -0.1, 0, 1), (0, 0, -1, 1), (0, 0, 0, -5), (None, 0, 0, 1)])
def test_invalid_inputs_raise(args):
    with pytest.raises(ValueError):
        assess_checkpoint(*args)

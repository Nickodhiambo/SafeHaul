"""Per-checkpoint weather risk classification.

Units expected from the weather layer:
    wind_mph      sustained/gust wind speed in miles per hour
    rain_in_hr    rain rate in inches per hour
    snow_in_hr    snowfall rate in inches per hour
    load_lb       load weight in pounds

Boundary rules (documented because the assessment table overlaps at the edges):
    Wind          lower bound inclusive:  >=25 Moderate, >=35 High, >=45 Severe, >=55 No Travel
    Rain / Snow   "No Travel" is strictly greater than the stated limit (>1.00, >3.0), so the
                  upper edge of each band is inclusive:
                      Rain: Low <0.10 | Moderate 0.10-0.25 | High >0.25-0.50 | Severe >0.50-1.00 | No Travel >1.00
                      Snow: Low <0.5  | Moderate 0.5-1.0   | High >1.0-2.0   | Severe >2.0-3.0   | No Travel >3.0
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class RiskLevel(IntEnum):
    """Ordered so that max() picks the worst level and the value doubles as a score."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").title()


# Load-rule constants
NO_TRAVEL_WIND_ANY_LOAD_MPH = 55
HEAVY_LOAD_NO_TRAVEL_LB = 30_000  # with 45-54 mph wind
VERY_HEAVY_LOAD_SEVERE_LB = 40_000  # with 35-44 mph wind

# (threshold, level, inclusive). Checked from the worst level down.
_Band = tuple[float, RiskLevel, bool]

WIND_BANDS: tuple[_Band, ...] = (
    (55, RiskLevel.NO_TRAVEL, True),
    (45, RiskLevel.SEVERE, True),
    (35, RiskLevel.HIGH, True),
    (25, RiskLevel.MODERATE, True),
)
RAIN_BANDS: tuple[_Band, ...] = (
    (1.00, RiskLevel.NO_TRAVEL, False),
    (0.50, RiskLevel.SEVERE, False),
    (0.25, RiskLevel.HIGH, False),
    (0.10, RiskLevel.MODERATE, True),
)
SNOW_BANDS: tuple[_Band, ...] = (
    (3.0, RiskLevel.NO_TRAVEL, False),
    (2.0, RiskLevel.SEVERE, False),
    (1.0, RiskLevel.HIGH, False),
    (0.5, RiskLevel.MODERATE, True),
)


def _classify(value: float, bands: tuple[_Band, ...]) -> RiskLevel:
    for threshold, level, inclusive in bands:
        if value > threshold or (inclusive and value == threshold):
            return level
    return RiskLevel.LOW


def classify_wind(wind_mph: float) -> RiskLevel:
    return _classify(_check(wind_mph, "wind_mph"), WIND_BANDS)


def classify_rain(rain_in_hr: float) -> RiskLevel:
    return _classify(_check(rain_in_hr, "rain_in_hr"), RAIN_BANDS)


def classify_snow(snow_in_hr: float) -> RiskLevel:
    return _classify(_check(snow_in_hr, "snow_in_hr"), SNOW_BANDS)


def apply_load_rules(level: RiskLevel, wind_mph: float, load_lb: float) -> RiskLevel:
    """Escalate a weather-only level using the load rules. Never lowers a level."""
    if wind_mph >= NO_TRAVEL_WIND_ANY_LOAD_MPH:
        return RiskLevel.NO_TRAVEL
    if 45 <= wind_mph < 55 and load_lb > HEAVY_LOAD_NO_TRAVEL_LB:
        return RiskLevel.NO_TRAVEL
    if 35 <= wind_mph < 45 and load_lb > VERY_HEAVY_LOAD_SEVERE_LB:
        return max(level, RiskLevel.SEVERE)
    return level


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    wind_level: RiskLevel
    rain_level: RiskLevel
    snow_level: RiskLevel
    load_adjusted: bool  # True if the load rules raised the level above the weather-only level
    driver: str  # "wind" | "rain" | "snow" | "load" | "none"
    reason: str  # human readable, shown in the UI

    def to_dict(self) -> dict:
        return {
            "level": self.level.label,
            "score": int(self.level),
            "wind_level": self.wind_level.label,
            "rain_level": self.rain_level.label,
            "snow_level": self.snow_level.label,
            "load_adjusted": self.load_adjusted,
            "driver": self.driver,
            "reason": self.reason,
        }


def assess_checkpoint(
    wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_lb: float
) -> RiskAssessment:
    """Overall risk at one checkpoint = worst of wind/rain/snow, then load-rule escalation."""
    _check(load_lb, "load_lb")
    wind_level = classify_wind(wind_mph)
    rain_level = classify_rain(rain_in_hr)
    snow_level = classify_snow(snow_in_hr)

    weather_level = max(wind_level, rain_level, snow_level)
    final_level = apply_load_rules(weather_level, wind_mph, load_lb)
    load_adjusted = final_level > weather_level

    if load_adjusted:
        driver = "load"
        reason = f"Wind {wind_mph:g} mph with a {load_lb:,.0f} lb load → {final_level.label}"
    elif final_level == RiskLevel.LOW:
        driver = "none"
        reason = "Conditions within safe limits"
    else:
        # Ties resolve wind > rain > snow
        driver, value, unit = max(
            (("wind", wind_mph, "mph"), ("rain", rain_in_hr, "in/hr"), ("snow", snow_in_hr, "in/hr")),
            key=lambda d: {"wind": wind_level, "rain": rain_level, "snow": snow_level}[d[0]],
        )
        reason = f"{driver.capitalize()} {value:g} {unit} → {final_level.label}"

    return RiskAssessment(
        level=final_level,
        wind_level=wind_level,
        rain_level=rain_level,
        snow_level=snow_level,
        load_adjusted=load_adjusted,
        driver=driver,
        reason=reason,
    )


def _check(value: float, name: str) -> float:
    if value is None or value < 0:
        raise ValueError(f"{name} must be a non-negative number, got {value!r}")
    return value

"""Service construction. One shared instance per process so the weather cache persists
across requests. Tests replace `get_services`."""
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

from services.geocoding import GeocodingClient
from services.routing import RoutingClient
from services.weather import WeatherClient


@dataclass(frozen=True)
class Services:
    routing: RoutingClient
    weather: WeatherClient
    geocoding: GeocodingClient


@lru_cache(maxsize=1)
def get_services() -> Services:
    return Services(
        routing=RoutingClient(settings.MAPBOX_TOKEN),
        weather=WeatherClient(wind_metric=settings.WEATHER_WIND_METRIC),
        geocoding=GeocodingClient(settings.MAPBOX_TOKEN, country=settings.GEOCODE_COUNTRY),
    )

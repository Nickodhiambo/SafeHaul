import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from services.analysis import InvalidTrip, Location, analyze_trip
from services.geocoding import GeocodingError, GeocodingUnavailable, PlaceNotFound
from services.routing import NoRouteFound, RoutingError, RoutingUnavailable
from services.weather import ForecastRangeError, WeatherError, WeatherUnavailable

from . import deps
from .serializers import AnalyzeRequestSerializer

logger = logging.getLogger(__name__)

@api_view(['GET'])
def health(request):
    return Response({'status': 'OK'})


def _error(code: str, message: str, http_status: int, **extra) -> Response:
    return Response({"error": {"code": code, "message": message, **extra}}, status=http_status)


def _to_location(data: dict, geocoder) -> Location:
    if "lat" in data:
        return Location(data["lat"], data["lon"], data.get("label", ""))
    place = geocoder.resolve(data["query"])
    return Location(place.lat, place.lon, place.label)


@api_view(["GET"])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
def geocode(request):
    """Autocomplete suggestions: GET /api/geocode/?q=chic[&lat=..&lon=..]"""
    proximity = None
    try:
        if "lat" in request.query_params and "lon" in request.query_params:
            proximity = (float(request.query_params["lat"]), float(request.query_params["lon"]))
    except ValueError:
        return _error("invalid_request", "lat and lon must be numbers.", status.HTTP_400_BAD_REQUEST)

    try:
        places = deps.get_services().geocoding.search(
            request.query_params.get("q", ""), proximity=proximity
        )
    except ValueError as e:
        return _error("invalid_request", str(e), status.HTTP_400_BAD_REQUEST)
    except GeocodingUnavailable:
        return _error("upstream_unavailable", "Place search is temporarily unavailable.", status.HTTP_502_BAD_GATEWAY)
    except GeocodingError:
        logger.exception("Geocoding failed")
        return _error("upstream_error", "Place search failed.", status.HTTP_502_BAD_GATEWAY)
    return Response({"results": [p.to_dict() for p in places]})


@api_view(["POST"])
def analyze(request):
    """Analyze all route options for a trip and recommend the safest."""
    serializer = AnalyzeRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return _error(
            "invalid_request", "Please check the trip details.", status.HTTP_400_BAD_REQUEST,
            fields=serializer.errors,
        )
    data = serializer.validated_data

    try:
        services = deps.get_services()
        origin = _to_location(data["origin"], services.geocoding)
        destination = _to_location(data["destination"], services.geocoding)
        result = analyze_trip(
            origin, destination, data["departure"], data["load_lb"],
            routing=services.routing, weather=services.weather,
        )
    except InvalidTrip as e:
        return _error("invalid_trip", str(e), status.HTTP_400_BAD_REQUEST)
    except PlaceNotFound as e:
        return _error("place_not_found", str(e), status.HTTP_404_NOT_FOUND)
    except NoRouteFound as e:
        return _error("no_route", str(e), status.HTTP_404_NOT_FOUND)
    except ForecastRangeError:
        return _error(
            "forecast_unavailable",
            "Weather forecasts cover the next 16 days. Pick a departure time within that window.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except (WeatherUnavailable, RoutingUnavailable, GeocodingUnavailable):
        logger.warning("Upstream service unavailable", exc_info=True)
        return _error(
            "upstream_unavailable",
            "A routing or weather service is temporarily unavailable. Please try again.",
            status.HTTP_502_BAD_GATEWAY,
        )
    except (RoutingError, GeocodingError, WeatherError):
        logger.exception("Upstream service error")
        return _error("upstream_error", "The analysis could not be completed.", status.HTTP_502_BAD_GATEWAY)

    return Response(result)

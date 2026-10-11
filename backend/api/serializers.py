"""Request validation for the API."""
from datetime import timedelta, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from services.heatmap import MAX_HOURS, MAX_POINTS

MAX_LOAD_LB = 150_000  # legal US max is ~80,000 lb; leave headroom for oversize loads
PAST_GRACE = timedelta(hours=1)


def parse_departure(value: str):
    """ISO 8601 string with a timezone offset -> aware UTC datetime. Rejects past times."""
    try:
        dt = parse_datetime(value)
    except ValueError:
        dt = None
    if dt is None:
        raise serializers.ValidationError("Use an ISO 8601 date and time, e.g. 2026-10-12T08:00:00Z.")
    if dt.tzinfo is None:
        raise serializers.ValidationError(
            "Include a timezone offset, e.g. 2026-10-12T08:00:00Z or 2026-10-12T11:00:00+03:00."
        )
    dt = dt.astimezone(dt_timezone.utc)
    if dt < timezone.now() - PAST_GRACE:
        raise serializers.ValidationError("Departure time is in the past.")
    return dt


class PlaceInputSerializer(serializers.Serializer):
    """Either exact coordinates (picked from autocomplete) or free text to geocode."""

    lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    lon = serializers.FloatField(required=False, min_value=-180, max_value=180)
    label = serializers.CharField(required=False, allow_blank=True, max_length=200)
    query = serializers.CharField(required=False, max_length=256)

    def validate(self, attrs):
        has_lat, has_lon = "lat" in attrs, "lon" in attrs
        if has_lat != has_lon:
            raise serializers.ValidationError("Provide both lat and lon.")
        if not has_lat and not attrs.get("query", "").strip():
            raise serializers.ValidationError("Provide lat/lon or a place name.")
        return attrs


class AnalyzeRequestSerializer(serializers.Serializer):
    origin = PlaceInputSerializer()
    destination = PlaceInputSerializer()
    departure = serializers.CharField()
    load_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)

    def validate_departure(self, value):
        return parse_departure(value)


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class HeatmapRequestSerializer(serializers.Serializer):
    points = serializers.ListField(child=PointSerializer(), min_length=1, max_length=MAX_POINTS)
    start = serializers.CharField()  # the departure time
    load_lb = serializers.FloatField(min_value=0, max_value=MAX_LOAD_LB)
    hours = serializers.IntegerField(min_value=1, max_value=MAX_HOURS, default=MAX_HOURS)

    def validate_start(self, value):
        return parse_departure(value)

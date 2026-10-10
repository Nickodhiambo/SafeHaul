"""Place search / geocoding via the Mapbox Geocoding API (v6).

    search(query)   -> up to 5 suggestions for the form's autocomplete
    resolve(query)  -> the single best match, for when the user typed a place but never
                       picked a suggestion

Notes:
    * Results are returned as `Place` objects with (lat, lon), matching the rest of the
      backend's coordinate convention. Mapbox itself uses [lon, lat].
    * Mapbox's default geocoding is "temporary": results must not be stored long term, so
      nothing here is cached or persisted. Debounce keystrokes on the frontend instead.
    * `country` limits suggestions (comma-separated ISO codes, e.g. "us,ca"). Left unset by
      default; set it from settings if you want US/Canada-only suggestions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

GEOCODE_URL = "https://api.mapbox.com/search/geocode/v6/forward"
MIN_QUERY_CHARS = 2
MAX_QUERY_CHARS = 256
MAX_LIMIT = 10


class GeocodingError(Exception):
    pass


class PlaceNotFound(GeocodingError):
    pass


class GeocodingUnavailable(GeocodingError):
    """Network failure, rate limit or server error from the geocoding provider."""


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    label: str  # full display string, e.g. "Chicago, Illinois, United States"
    lat: float
    lon: float
    feature_type: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "label": self.label,
            "lat": self.lat,
            "lon": self.lon,
            "type": self.feature_type,
        }


def parse_features(payload: object) -> list[Place]:
    """GeoJSON FeatureCollection -> Places. Skips countries and features without coordinates."""
    if not isinstance(payload, dict):
        raise GeocodingUnavailable("Unexpected geocoding response")
    places = []
    for f in payload.get("features") or []:
        try:
            props = f.get("properties") or {}
            lon, lat = f["geometry"]["coordinates"][:2]
            ftype = props.get("feature_type", "")
            if ftype == "country":
                continue
            name = props.get("name_preferred") or props.get("name") or ""
            label = props.get("full_address") or ", ".join(
                p for p in (name, props.get("place_formatted")) if p
            )
            if not label:
                continue
            places.append(
                Place(
                    id=str(props.get("mapbox_id") or f.get("id") or label),
                    name=name or label,
                    label=label,
                    lat=float(lat),
                    lon=float(lon),
                    feature_type=ftype,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue  # one malformed feature shouldn't hide the rest
    return places


def default_http_get(url: str, params: dict, timeout: float = 10):
    import requests  # lazy so unit tests don't need it

    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        # str(e) can contain the request URL (and token), so don't include it
        raise GeocodingUnavailable(f"Geocoding request failed ({type(e).__name__})") from None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code in (401, 403):
        raise GeocodingError("Mapbox rejected the access token")
    if resp.status_code == 429 or resp.status_code >= 500:
        raise GeocodingUnavailable(f"Geocoding service returned HTTP {resp.status_code}")
    try:
        message = resp.json().get("message", "")
    except ValueError:
        message = ""
    raise GeocodingError(f"Geocoding request rejected (HTTP {resp.status_code}): {message}".strip())


class GeocodingClient:
    def __init__(
        self,
        token: str,
        *,
        http_get: Callable[[str, dict], object] = default_http_get,
        country: str | None = None,
        types: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 1,
    ):
        if not token:
            raise GeocodingError("MAPBOX_TOKEN is not configured")
        self._token = token
        self._http_get = http_get
        self._country = country
        self._types = types
        self._sleep = sleep
        self._retries = retries

    def search(
        self, query: str, *, limit: int = 5, proximity: tuple[float, float] | None = None
    ) -> list[Place]:
        """Autocomplete suggestions. `proximity` is (lat, lon) to bias results near a point."""
        q = (query or "").strip()
        if len(q) < MIN_QUERY_CHARS:
            return []
        if len(q) > MAX_QUERY_CHARS:
            raise ValueError(f"query is longer than {MAX_QUERY_CHARS} characters")

        params = {
            "q": q,
            "limit": min(max(limit, 1), MAX_LIMIT),
            "autocomplete": "true",
            "access_token": self._token,
        }
        if self._country:
            params["country"] = self._country
        if self._types:
            params["types"] = self._types
        if proximity:
            params["proximity"] = f"{proximity[1]:.5f},{proximity[0]:.5f}"  # Mapbox wants lon,lat

        payload = self._with_retries(lambda: self._http_get(GEOCODE_URL, params))
        return parse_features(payload)

    def resolve(self, query: str) -> Place:
        """Best single match for a typed place name."""
        if not (query or "").strip():
            raise ValueError("query is empty")
        places = self.search(query, limit=3)  # a few, since countries are filtered out
        if not places:
            raise PlaceNotFound(f"Couldn't find a place matching '{query.strip()}'")
        return places[0]

    def _with_retries(self, call):
        for attempt in range(self._retries + 1):
            try:
                return call()
            except GeocodingUnavailable:
                if attempt == self._retries:
                    raise
                self._sleep(0.3 * 2**attempt)

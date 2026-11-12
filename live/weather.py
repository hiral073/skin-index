import copy
import math
import re
import time

import requests

# Open-Meteo, free for non-commercial use, no API key. Every call has a timeout and goes
# through a small in-memory cache so repeat visits do not call the API again.
WEATHER_CONFIG = {
    "geocoding_url": "https://geocoding-api.open-meteo.com/v1/search",
    "forecast_url": "https://api.open-meteo.com/v1/forecast",
    "air_quality_url": "https://air-quality-api.open-meteo.com/v1/air-quality",
    "timeout_seconds": 5,
    "max_places": 5,
    "cache_seconds": 15 * 60,         # a successful answer is reused this long
    "failure_cache_seconds": 10,      # a failure is remembered this long, so reloads in an outage are not hammered
    "cache_max_entries": 200,         # oldest entries go first, so odd city names cannot grow it forever
}

# Plausible ranges: a value outside is treated as missing, never repaired or made up
VALID_RANGES = {
    "latitude": (-90, 90), "longitude": (-180, 180),
    "temperature_c": (-90, 60), "humidity": (0, 100), "uv": (0, 30),
    "us_aqi": (0, 1000), "pm2_5": (0, 2000),
}

_LOCAL_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

_clock = time.monotonic          # tests replace this to move time forward
_cache = {}                      # key -> (expires_at, "ok" or "error", value or message)


class WeatherError(Exception):
    """The weather or place service could not be reached or its answer could not be used."""


def clear_cache():
    _cache.clear()


def _number(value, kind):
    """value as a float when it is a real number inside the plausible range for `kind`, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    low, high = VALID_RANGES[kind]
    return float(value) if low <= value <= high else None


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _local_time(value):
    return value if isinstance(value, str) and _LOCAL_TIME.match(value) else None


def _get_json(url, params):
    try:
        response = requests.get(url, params=params, timeout=WEATHER_CONFIG["timeout_seconds"])
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError(f"Could not reach the weather service: {exc}") from exc
    if not isinstance(data, dict):
        raise WeatherError("The weather service sent a reply we could not read.")
    if data.get("error"):
        raise WeatherError(f"The weather service refused the request: {data.get('reason', 'unknown reason')}")
    return data


def _cached(key, fetch):
    now = _clock()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        if hit[1] == "error":
            raise WeatherError(hit[2])
        return copy.deepcopy(hit[2])
    try:
        value = fetch()
    except WeatherError as exc:
        _store(key, now + WEATHER_CONFIG["failure_cache_seconds"], "error", str(exc))
        raise
    _store(key, now + WEATHER_CONFIG["cache_seconds"], "ok", copy.deepcopy(value))
    return value


def _store(key, expires_at, kind, value):
    if key not in _cache and len(_cache) >= WEATHER_CONFIG["cache_max_entries"]:
        now = _clock()
        for old in [k for k, (expiry, *_rest) in _cache.items() if expiry <= now]:
            del _cache[old]
        if len(_cache) >= WEATHER_CONFIG["cache_max_entries"]:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
    _cache[key] = (expires_at, kind, value)


def search_places(name):
    """Up to 5 places matching `name`: [{"name", "region", "country", "latitude", "longitude",
    "timezone"}]; an empty list when nothing matches. Raises WeatherError if the lookup fails."""
    return _cached(("places", name.casefold()), lambda: _search_places(name))


def _search_places(name):
    data = _get_json(WEATHER_CONFIG["geocoding_url"], {
        "name": name, "count": WEATHER_CONFIG["max_places"], "language": "en", "format": "json",
    })
    places = []
    for item in (data.get("results") or [])[:WEATHER_CONFIG["max_places"]]:   # no match: no "results" key at all
        if not isinstance(item, dict):
            continue
        latitude, longitude = _number(item.get("latitude"), "latitude"), _number(item.get("longitude"), "longitude")
        if _text(item.get("name")) is None or latitude is None or longitude is None:
            continue
        places.append({
            "name": _text(item["name"]), "region": _text(item.get("admin1")),
            "country": _text(item.get("country")), "latitude": latitude, "longitude": longitude,
            "timezone": _text(item.get("timezone")),
        })
    return places


def _grid(latitude, longitude):
    return round(latitude, 2), round(longitude, 2)


def fetch_forecast(latitude, longitude):
    """Current temperature, humidity and UV index, today's maximum UV and today's hourly UV, at
    local time: {"time", "temperature_c", "humidity", "uv_now", "uv_max", "uv_hourly"}.
    uv_hourly is [{"time": "YYYY-MM-DDTHH:MM", "uv"}]; each value is the average of the hour
    that ENDS at that time (Open-Meteo's definition). A value that is missing or implausible is
    None (or left out of uv_hourly). Raises WeatherError if nothing usable comes back."""
    latitude, longitude = _grid(latitude, longitude)
    return _cached(("forecast", latitude, longitude), lambda: _fetch_forecast(latitude, longitude))


def _fetch_forecast(latitude, longitude):
    data = _get_json(WEATHER_CONFIG["forecast_url"], {
        "latitude": latitude, "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,uv_index",
        "hourly": "uv_index", "daily": "uv_index_max", "forecast_days": 1, "timezone": "auto",
    })
    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}
    maxima = daily.get("uv_index_max")
    hourly = data.get("hourly") if isinstance(data.get("hourly"), dict) else {}
    uv_hourly = []
    if isinstance(hourly.get("time"), list) and isinstance(hourly.get("uv_index"), list):
        for stamp, value in zip(hourly["time"], hourly["uv_index"]):
            stamp, uv = _local_time(stamp), _number(value, "uv")
            if stamp is not None and uv is not None:
                uv_hourly.append({"time": stamp[:16], "uv": uv})
    result = {
        "time": _local_time(current.get("time")),
        "temperature_c": _number(current.get("temperature_2m"), "temperature_c"),
        "humidity": _number(current.get("relative_humidity_2m"), "humidity"),
        "uv_now": _number(current.get("uv_index"), "uv"),
        "uv_max": _number(maxima[0], "uv") if isinstance(maxima, list) and maxima else None,
        "uv_hourly": uv_hourly,
    }
    if all(result[key] is None for key in ("temperature_c", "humidity", "uv_now", "uv_max")) and not uv_hourly:
        raise WeatherError("The weather service had no usable conditions for this place.")
    return result


def fetch_air_quality(latitude, longitude):
    """Current US AQI and PM2.5: {"time", "us_aqi", "pm2_5"}; a missing value is None.
    Raises WeatherError if nothing usable comes back."""
    latitude, longitude = _grid(latitude, longitude)
    return _cached(("air", latitude, longitude), lambda: _fetch_air_quality(latitude, longitude))


def _fetch_air_quality(latitude, longitude):
    data = _get_json(WEATHER_CONFIG["air_quality_url"], {
        "latitude": latitude, "longitude": longitude,
        "current": "us_aqi,pm2_5", "timezone": "auto",
    })
    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    result = {
        "time": _local_time(current.get("time")),
        "us_aqi": _number(current.get("us_aqi"), "us_aqi"),
        "pm2_5": _number(current.get("pm2_5"), "pm2_5"),
    }
    if result["us_aqi"] is None and result["pm2_5"] is None:
        raise WeatherError("The air quality service had no usable values for this place.")
    return result

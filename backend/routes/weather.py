"""
weather.py
──────────
Weather data for KrishiSetu.

Fetch chain (most accurate → most available):
  1. Geocode location string → lat/lon  (Nominatim / OpenCage, free)
  2. Open-Meteo current weather by lat/lon  (completely free, no key)
  3. OpenWeatherMap by city name  (existing OWM key, used as fallback)
  4. Seasonal defaults  (always safe, never throws)

All existing public interfaces are unchanged:
  • _fetch_weather(city) → dict     (used by recommendation_service.py)
  • GET /weather?city=… | ?location=…  (used by frontend)
"""

from __future__ import annotations

import datetime
import requests
from flask import Blueprint, jsonify, request


weather_bp = Blueprint("weather", __name__)

# ── OpenWeatherMap (existing key — kept as fallback) ──────────────────────────
_OWM_API_KEY = "b18e9705aaddf8a77f0f9d791e6cc0cb"
_OWM_URL     = "https://api.openweathermap.org/data/2.5/weather"

# ── Open-Meteo (completely free, no key needed) ───────────────────────────────
_OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code"
    "&timezone=auto"
)

# WMO weather interpretation codes → human-readable condition string
_WMO_CONDITIONS: dict[int, str] = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy Fog",
    51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Dense Drizzle",
    61: "Slight Rain", 63: "Moderate Rain", 65: "Heavy Rain",
    71: "Slight Snow", 73: "Moderate Snow", 75: "Heavy Snow",
    80: "Slight Showers", 81: "Moderate Showers", 82: "Violent Showers",
    95: "Thunderstorm", 96: "Thunderstorm with Hail", 99: "Severe Thunderstorm",
}


# ─────────────────────────────────────────────────────────────────────────────
# SEASONAL RAINFALL HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _season_rainfall_mm(month: int) -> float:
    """
    Indian climatological monthly rainfall estimate (0-indexed month).
    Used as fallback when no live precipitation data is available.
      Kharif (Jun–Sep) : monsoon    → 180 mm
      Rabi   (Oct–Jan) : winter     →  35 mm
      Zaid   (Feb–May) : summer     →  60 mm
    """
    if 5 <= month <= 8:
        return 180.0
    if month >= 9 or month <= 0:
        return 35.0
    return 60.0


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER 1: OPEN-METEO  (free, coordinate-based)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_open_meteo(lat: float, lon: float) -> dict:
    """
    Fetch current weather from Open-Meteo using lat/lon.

    Returns a normalised dict with keys:
      temperature, humidity, rainfall (hourly mm), condition, source

    Returns an empty dict on any failure — caller falls back to OWM.
    """
    try:
        url = _OPEN_METEO_URL.format(lat=lat, lon=lon)
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()

        current = payload.get("current") or {}
        temp    = current.get("temperature_2m")
        hum     = current.get("relative_humidity_2m")
        precip  = current.get("precipitation")        # mm in the last hour
        code    = current.get("weather_code", 0)

        if temp is None or hum is None:
            return {}

        condition = _WMO_CONDITIONS.get(int(code), f"Code {code}")
        print(
            f"[Weather/OpenMeteo] ({lat:.3f},{lon:.3f}) -> "
            f"temp={temp}C hum={hum}% precip={precip}mm cond='{condition}'"
        )
        return {
            "temperature": float(temp),
            "humidity":    float(hum),
            "rainfall":    float(precip) if precip is not None else None,
            "condition":   condition,
            "source":      "open-meteo",
        }
    except Exception as exc:
        print(f"[Weather/OpenMeteo] Failed ({lat},{lon}): {exc}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER 2: OPENWEATHERMAP  (existing key, city-name fallback)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_owm(city: str) -> dict:
    """
    Fetch current weather from OpenWeatherMap by city name.
    Returns a normalised dict or empty dict on failure.
    """
    if not city or not _OWM_API_KEY:
        return {}
    try:
        resp = requests.get(
            _OWM_URL,
            params={"q": city, "appid": _OWM_API_KEY, "units": "metric"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {}
        payload = resp.json()
        main    = payload.get("main") or {}
        rain    = payload.get("rain") or {}
        arr     = payload.get("weather") or []

        temp = main.get("temp")
        hum  = main.get("humidity")
        if temp is None or hum is None:
            return {}

        condition = "Unknown"
        if arr and isinstance(arr[0], dict):
            condition = str(arr[0].get("description") or "Unknown").title()

        hourly_rain = rain.get("1h") or rain.get("3h")
        print(
            f"[Weather/OWM] '{city}' -> temp={temp}C hum={hum}% "
            f"rain={hourly_rain}mm cond='{condition}'"
        )
        return {
            "temperature": float(temp),
            "humidity":    float(hum),
            "rainfall":    float(hourly_rain) if hourly_rain is not None else None,
            "condition":   condition,
            "source":      "owm",
        }
    except Exception as exc:
        print(f"[Weather/OWM] Failed for '{city}': {exc}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC HELPER  (_fetch_weather)
# Signature is UNCHANGED — all existing callers work without modification.
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_weather(city: str) -> dict:
    """
    Resolve *city* (any free-text location string) to live weather data.

    Fetch chain:
      1. Geocode city → lat/lon  (Nominatim, free)
      2. Open-Meteo  at lat/lon  (free, most accurate)
      3. OWM         by city name (existing key, fallback)
      4. Return dict with source="default" and None values → caller uses defaults

    Returns a dict with keys:
      temperature (°C), humidity (%), rainfall (mm/h or None),
      condition (str), source ("open-meteo" | "owm" | "default")

    NEVER raises — always returns a safe dict.
    """
    city = str(city or "").strip()
    empty = {
        "temperature": None, "humidity": None,
        "rainfall": None, "condition": "Unknown", "source": "default",
    }
    if not city:
        return empty

    # ── Step 1: geocode ──────────────────────────────────────────────────────
    lat, lon = None, None
    try:
        from services.geolocation_service import get_lat_lon
        lat, lon = get_lat_lon(city)
    except Exception as geo_exc:
        print(f"[Weather] Geocoding import/call failed: {geo_exc}")

    # ── Step 2: Open-Meteo (if we have coordinates) ──────────────────────────
    if lat is not None and lon is not None:
        result = _fetch_open_meteo(lat, lon)
        if result:
            return result

    # ── Step 3: OpenWeatherMap by city name (fallback) ───────────────────────
    result = _fetch_owm(city)
    if result:
        return result

    # ── Step 4: total failure ────────────────────────────────────────────────
    print(f"[Weather] All providers failed for '{city}' — returning empty dict")
    return empty


# ─────────────────────────────────────────────────────────────────────────────
# FLASK ROUTE  — unchanged API contract
# GET /weather?city=<name>   OR   GET /weather?location=<name>
# ─────────────────────────────────────────────────────────────────────────────
@weather_bp.get("")
def get_weather():
    """
    Always returns HTTP 200 with a complete weather dict so the frontend
    is never left with empty fields.

    Response:
      {
        "success": true,
        "data": {
          "temperature": <float °C>,
          "humidity":    <float %>,
          "rainfall":    <float mm/month estimate>,
          "condition":   <string>,
          "source":      "open-meteo" | "owm" | "default"
        }
      }
    """
    location = (
        str(request.args.get("city")     or "").strip()
        or str(request.args.get("location") or "").strip()
    )

    month = datetime.datetime.utcnow().month - 1   # 0-indexed

    defaults = {
        "temperature": 25.0,
        "humidity":    60.0,
        "rainfall":    _season_rainfall_mm(month),
        "condition":   "N/A (default)",
        "source":      "default",
    }

    if not location:
        return jsonify({"success": True, "data": defaults}), 200

    raw = _fetch_weather(location)

    if raw.get("source") == "default" or raw.get("temperature") is None:
        return jsonify({"success": True, "data": defaults}), 200

    # Convert hourly precipitation to approximate monthly equivalent
    hourly_rain = raw.get("rainfall")
    if hourly_rain is not None:
        monthly_rain = round(min(float(hourly_rain) * 720, 400.0), 1)
    else:
        monthly_rain = _season_rainfall_mm(month)

    data = {
        "temperature": round(float(raw["temperature"]), 1),
        "humidity":    round(float(raw["humidity"]), 1),
        "rainfall":    monthly_rain,
        "condition":   raw.get("condition", "Unknown"),
        "source":      raw.get("source", "default"),
    }
    return jsonify({"success": True, "data": data}), 200

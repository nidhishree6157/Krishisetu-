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
_OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

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
    Fetch current + hourly (24 h) + daily (7 day) weather from Open-Meteo.

    Returns a normalised dict with keys:
      temperature, humidity, rainfall, condition, wind, pressure, uv_index,
      source, hourly (list), daily (list)

    Returns an empty dict on any failure — caller falls back to OWM.
    """
    try:
        url = (
            f"{_OPEN_METEO_BASE}"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,"
            f"weather_code,wind_speed_10m,surface_pressure"
            f"&hourly=temperature_2m,weather_code,precipitation_probability,uv_index"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min,"
            f"precipitation_sum,uv_index_max,wind_speed_10m_max"
            f"&timezone=auto&forecast_days=7"
        )
        resp = requests.get(url, timeout=12)
        resp.raise_for_status()
        payload = resp.json()

        # ── Current ──────────────────────────────────────────────────────────
        current = payload.get("current") or {}
        temp     = current.get("temperature_2m")
        hum      = current.get("relative_humidity_2m")
        precip   = current.get("precipitation")
        code     = current.get("weather_code", 0)
        wind     = current.get("wind_speed_10m")
        pressure = current.get("surface_pressure")
        cur_time = current.get("time", "")

        if temp is None or hum is None:
            return {}

        condition = _WMO_CONDITIONS.get(int(code), f"Code {code}")
        print(
            f"[Weather/OpenMeteo] ({lat:.3f},{lon:.3f}) -> "
            f"temp={temp}C hum={hum}% wind={wind}km/h cond='{condition}'"
        )

        # ── Hourly (next 24 h starting from current observation) ─────────────
        hourly_raw   = payload.get("hourly") or {}
        h_times      = hourly_raw.get("time") or []
        h_temps      = hourly_raw.get("temperature_2m") or []
        h_codes      = hourly_raw.get("weather_code") or []
        h_probs      = hourly_raw.get("precipitation_probability") or []
        h_uvs        = hourly_raw.get("uv_index") or []

        # Locate current hour in the hourly array
        try:
            cur_idx = h_times.index(cur_time)
        except ValueError:
            cur_idx = 0

        # Current UV from hourly
        current_uv = h_uvs[cur_idx] if cur_idx < len(h_uvs) else None

        hourly_forecast = []
        for i in range(cur_idx, min(cur_idx + 24, len(h_times))):
            t = h_times[i]
            time_label = t[11:16] if len(t) > 10 else t   # "HH:MM" from ISO
            hourly_forecast.append({
                "time":        time_label,
                "temp":        round(float(h_temps[i]), 1) if i < len(h_temps) and h_temps[i] is not None else None,
                "code":        int(h_codes[i]) if i < len(h_codes) and h_codes[i] is not None else 0,
                "precip_prob": int(h_probs[i]) if i < len(h_probs) and h_probs[i] is not None else 0,
            })

        # ── Daily (7 days) ───────────────────────────────────────────────────
        daily_raw  = payload.get("daily") or {}
        d_dates    = daily_raw.get("time") or []
        d_codes    = daily_raw.get("weather_code") or []
        d_maxes    = daily_raw.get("temperature_2m_max") or []
        d_mines    = daily_raw.get("temperature_2m_min") or []
        d_rains    = daily_raw.get("precipitation_sum") or []
        d_uvs      = daily_raw.get("uv_index_max") or []
        d_winds    = daily_raw.get("wind_speed_10m_max") or []

        daily_forecast = []
        for i, date in enumerate(d_dates):
            daily_forecast.append({
                "date":     date,
                "code":     int(d_codes[i]) if i < len(d_codes) and d_codes[i] is not None else 0,
                "max":      round(float(d_maxes[i]), 1) if i < len(d_maxes) and d_maxes[i] is not None else None,
                "min":      round(float(d_mines[i]), 1) if i < len(d_mines) and d_mines[i] is not None else None,
                "rain":     round(float(d_rains[i]), 1) if i < len(d_rains) and d_rains[i] is not None else 0.0,
                "uv_max":   round(float(d_uvs[i]), 1)  if i < len(d_uvs)   and d_uvs[i]   is not None else None,
                "wind_max": round(float(d_winds[i]), 1) if i < len(d_winds) and d_winds[i] is not None else None,
            })

        return {
            "temperature": float(temp),
            "humidity":    float(hum),
            "rainfall":    float(precip) if precip is not None else None,
            "condition":   condition,
            "wind":        round(float(wind), 1) if wind is not None else None,
            "pressure":    round(float(pressure), 1) if pressure is not None else None,
            "uv_index":    round(float(current_uv), 1) if current_uv is not None else None,
            "source":      "open-meteo",
            "hourly":      hourly_forecast,
            "daily":       daily_forecast,
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
        "wind":        raw.get("wind"),
        "pressure":    raw.get("pressure"),
        "uv_index":    raw.get("uv_index"),
        "source":      raw.get("source", "default"),
    }

    response_body: dict = {"success": True, "data": data}

    # Include extended forecast when Open-Meteo data is available
    if raw.get("hourly") or raw.get("daily"):
        response_body["forecast"] = {
            "hourly": raw.get("hourly", []),
            "daily":  raw.get("daily",  []),
        }

    return jsonify(response_body), 200

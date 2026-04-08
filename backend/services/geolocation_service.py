"""
geolocation_service.py
──────────────────────
Converts a free-text location string (e.g. "Bangalore, Karnataka") into a
(latitude, longitude) tuple for use with coordinate-based weather APIs.

Provider priority
─────────────────
1. Nominatim  (OpenStreetMap) — completely FREE, no API key required.
2. OpenCage   — free tier available; activated only when the env var
                OPENCAGE_API_KEY is set.  Never required.

Both providers are tried in order; the first successful result wins.
On any failure the function returns (None, None) so callers can apply
their own fallback logic without crashing.

Usage
─────
    from services.geolocation_service import get_lat_lon

    lat, lon = get_lat_lon("Bangalore, Karnataka")
    if lat and lon:
        # use coordinates …
"""

from __future__ import annotations

import os
import requests

# ── constants ─────────────────────────────────────────────────────────────────
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim terms require a meaningful User-Agent identifying your application.
_USER_AGENT = "KrishiSetu/1.0 (agricultural advisory platform)"
_NOMINATIM_TIMEOUT = 8   # seconds

_OPENCAGE_URL = "https://api.opencagedata.com/geocode/v1/json"
_OPENCAGE_KEY = os.environ.get("90c8bb85b5824c5193ed420294708dd6", "")   # optional
_OPENCAGE_TIMEOUT = 8


# ── geocoders ─────────────────────────────────────────────────────────────────

def _geocode_nominatim(location: str) -> tuple[float | None, float | None]:
    """
    Use Nominatim (OpenStreetMap) to resolve *location*.
    Free, no API key needed.  Rate-limited to 1 req/s — acceptable for
    on-demand user queries.
    """
    try:
        resp = requests.get(
            _NOMINATIM_URL,
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=_NOMINATIM_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            lat = float(results[0]["lat"])
            lon = float(results[0]["lon"])
            print(f"[Geo/Nominatim] '{location}' -> ({lat:.4f}, {lon:.4f})")
            return lat, lon
    except Exception as exc:
        print(f"[Geo/Nominatim] Failed for '{location}': {exc}")
    return None, None


def _geocode_opencage(location: str) -> tuple[float | None, float | None]:
    """
    Use OpenCage as a secondary geocoder.
    Only called when OPENCAGE_API_KEY env var is present.
    """
    if not _OPENCAGE_KEY:
        return None, None
    try:
        resp = requests.get(
            _OPENCAGE_URL,
            params={"q": location, "key": _OPENCAGE_KEY, "limit": 1},
            timeout=_OPENCAGE_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if results:
            geom = results[0].get("geometry") or {}
            lat = float(geom["lat"])
            lon = float(geom["lng"])
            print(f"[Geo/OpenCage] '{location}' -> ({lat:.4f}, {lon:.4f})")
            return lat, lon
    except Exception as exc:
        print(f"[Geo/OpenCage] Failed for '{location}': {exc}")
    return None, None


# ── public API ────────────────────────────────────────────────────────────────

def get_lat_lon(location: str) -> tuple[float | None, float | None]:
    """
    Convert a free-text *location* string to (latitude, longitude).

    Tries providers in order:
      1. Nominatim (always attempted, no key needed)
      2. OpenCage  (only if OPENCAGE_API_KEY env var is set)

    Returns (None, None) when all providers fail — callers must handle
    this gracefully (e.g. fall back to city-name-based weather lookup).

    Args:
        location: Human-readable place name, e.g. "Mysore, Karnataka"
                  or "Ludhiana, Punjab, India".  More specific strings
                  give better geocoding accuracy.

    Returns:
        (lat, lon) as floats, or (None, None) on failure.
    """
    location = str(location or "").strip()
    if not location:
        return None, None

    # Provider 1: Nominatim (free, always)
    lat, lon = _geocode_nominatim(location)
    if lat is not None and lon is not None:
        return lat, lon

    # Provider 2: OpenCage (free tier, key required)
    lat, lon = _geocode_opencage(location)
    if lat is not None and lon is not None:
        return lat, lon

    print(f"[Geo] All providers failed for '{location}'")
    return None, None

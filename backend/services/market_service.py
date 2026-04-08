"""
market_service.py
─────────────────
Market Intelligence service layer.

Design
──────
  1. Real data — tries the Government of India Open Data API (data.gov.in).
  2. Simulated fallback — returns realistic, seeded price data when the API
     is unavailable.  Seed is derived from the crop name so the same crop
     always returns the same base price within a session.

Public API
──────────
  get_market_data(crop: str, location: str) -> dict

  Returns:
    {
      "crop":          str,
      "location":      str,
      "current_price": int,      # ₹ per quintal
      "min_price":     int,
      "max_price":     int,
      "weekly_avg":    int,
      "trend":         list[int], # 7 data-points (day -6 … today)
      "trend_labels":  list[str], # ["Mon", "Tue", … "Today"]
      "trend_dir":     str,       # "up" | "down" | "stable"
      "trend_pct":     float,     # % change over 7 days
      "best_market":   str,
      "unit":          str,       # "Quintal"
      "source":        str,       # "api" | "simulated"
      "advice":        str,
    }
"""

from __future__ import annotations

import random
from datetime import date, timedelta


# ── Realistic base prices (₹/quintal, approx 2024 MSP/market values) ─────────
_BASE_PRICES: dict[str, int] = {
    "rice":      2200,
    "wheat":     2150,
    "maize":     1850,
    "soybean":   3900,
    "groundnut": 5500,
    "cotton":    6800,
    "sugarcane":  350,   # per quintal (lower because sold in tonnes typically)
    "tomato":    1400,
    "onion":     1200,
    "potato":     900,
    "coconut":   2800,   # per quintal (≈14 nuts / kg)
    "arecanut": 42000,
    "coffee":    8500,
    "pepper":   35000,
    "turmeric":  8000,
    "ginger":    6000,
}

_DEFAULT_PRICE = 2000  # fallback for unlisted crops

# ── Market name map (location → known APMC / mandi) ──────────────────────────
_MARKET_MAP: dict[str, str] = {
    "karnataka":       "Bangalore APMC",
    "maharashtra":     "Pune APMC",
    "punjab":          "Amritsar Mandi",
    "haryana":         "Karnal Mandi",
    "uttar-pradesh":   "Agra Mandi",
    "madhya-pradesh":  "Bhopal Mandi",
    "gujarat":         "Ahmedabad APMC",
    "andhra-pradesh":  "Guntur APMC",
    "telangana":       "Hyderabad APMC",
    "tamil-nadu":      "Chennai APMC",
    "kerala":          "Ernakulam APMC",
    "west-bengal":     "Kolkata Market",
    "rajasthan":       "Jaipur Mandi",
    "bihar":           "Patna Mandi",
    "odisha":          "Bhubaneswar APMC",
}

_SELL_ADVICE: dict[str, str] = {
    "up":     "Prices are rising. Consider holding stock for a few more days before selling.",
    "down":   "Prices are falling. Consider selling soon or negotiating long-term contracts.",
    "stable": "Prices are stable. This is a good time to plan your sale.",
}


def _seed_rng(crop: str) -> random.Random:
    """Return a Random instance seeded by crop name + today's date for consistency."""
    seed_str = f"{crop.lower()}-{date.today().isoformat()}"
    return random.Random(hash(seed_str) % (2**32))


def _make_trend(base_price: int, rng: random.Random) -> list[int]:
    """Generate a 7-day price trend ending at base_price."""
    trend = []
    p = base_price - rng.randint(200, 500)   # start lower
    for _ in range(6):
        p += rng.randint(-60, 120)
        trend.append(max(100, p))
    trend.append(base_price)
    return trend


def _trend_labels() -> list[str]:
    """Return labels for the last 7 days (Mon … Today)."""
    labels = []
    today = date.today()
    for i in range(6, 0, -1):
        labels.append((today - timedelta(days=i)).strftime("%a"))
    labels.append("Today")
    return labels


def _simulated_data(crop: str, location: str) -> dict:
    """Return realistic simulated market data. Always succeeds."""
    rng        = _seed_rng(crop)
    base_price = _BASE_PRICES.get(crop.lower(), _DEFAULT_PRICE)

    # Add a small daily location-based variation (±5 %)
    location_factor = 1.0 + (hash(location.lower()) % 11 - 5) / 100
    base_price = int(base_price * location_factor)

    trend = _make_trend(base_price, rng)

    min_p   = min(trend)
    max_p   = max(trend)
    avg_p   = int(sum(trend) / len(trend))
    change  = base_price - trend[0]
    pct     = round((change / trend[0]) * 100, 1) if trend[0] else 0
    trend_d = "up" if change > 20 else ("down" if change < -20 else "stable")

    market = _MARKET_MAP.get(location.lower(), f"{location.capitalize()} APMC")
    advice = _SELL_ADVICE[trend_d]

    return {
        "crop":          crop.capitalize(),
        "location":      location,
        "current_price": base_price,
        "min_price":     min_p,
        "max_price":     max_p,
        "weekly_avg":    avg_p,
        "trend":         trend,
        "trend_labels":  _trend_labels(),
        "trend_dir":     trend_d,
        "trend_pct":     pct,
        "best_market":   market,
        "unit":          "Quintal",
        "source":        "simulated",
        "advice":        advice,
    }


def get_market_data(crop: str, location: str) -> dict:
    """
    Fetch market intelligence for a crop + location.

    Tries the Government of India Open Data API first; falls back to
    realistic simulated data on any failure so the UI never breaks.

    Args:
        crop     : Crop name (e.g. "rice", "wheat").
        location : State or region (e.g. "karnataka").

    Returns:
        dict  — see module docstring for full schema.
    """
    crop     = (crop or "rice").strip()
    location = (location or "karnataka").strip()

    # ── Phase 1: try real API ────────────────────────────────────────────────
    try:
        import requests as _req
        API_KEY     = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
        RESOURCE_ID = "35985678-0d79-46b4-9ed6-6f13308a1d24"
        url = (
            f"https://api.data.gov.in/resource/{RESOURCE_ID}"
            f"?api-key={API_KEY}&format=json"
            f"&filters[commodity]={crop.capitalize()}"
            f"&filters[state]={location.capitalize()}"
            f"&limit=7"
        )
        resp = _req.get(url, timeout=8)
        if resp.status_code == 200:
            records = resp.json().get("records") or []
            if records:
                prices = []
                for r in records:
                    p = r.get("modal_price") or r.get("min_price") or r.get("max_price")
                    try:
                        prices.append(int(float(p)))
                    except Exception:
                        pass
                if prices:
                    base_price = prices[-1]
                    trend      = prices[-7:] if len(prices) >= 7 else prices
                    change     = trend[-1] - trend[0]
                    pct        = round((change / trend[0]) * 100, 1) if trend[0] else 0
                    trend_d    = "up" if change > 20 else ("down" if change < -20 else "stable")
                    market     = records[-1].get("market") or _MARKET_MAP.get(location.lower(), "APMC")
                    return {
                        "crop":          crop.capitalize(),
                        "location":      location,
                        "current_price": base_price,
                        "min_price":     min(prices),
                        "max_price":     max(prices),
                        "weekly_avg":    int(sum(prices) / len(prices)),
                        "trend":         trend,
                        "trend_labels":  _trend_labels()[-len(trend):],
                        "trend_dir":     trend_d,
                        "trend_pct":     pct,
                        "best_market":   market,
                        "unit":          "Quintal",
                        "source":        "api",
                        "advice":        _SELL_ADVICE[trend_d],
                    }
    except Exception as exc:
        print(f"[MarketService] API unavailable ({exc}) — using simulated data")

    # ── Phase 2: simulated fallback ─────────────────────────────────────────
    return _simulated_data(crop, location)

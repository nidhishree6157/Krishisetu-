"""
yield_service.py
────────────────
Rule-based yield prediction service.

Algorithm
─────────
  predicted_yield (kg/ha) = base_yield × rainfall_factor × temperature_factor
                            × soil_factor × irrigation_factor

  total_yield (kg)        = predicted_yield × area_ha

  confidence              = 0.95 − (sum of per-factor penalties)  ∈ [0.70, 0.95]

All factor functions return a float in [0.60, 1.15].  Values > 1.0 mean
conditions are better than average; values < 1.0 indicate stress.

Public API
──────────
  predict_yield(data: dict) -> dict

  Input keys (all optional — safe defaults used if missing):
    crop         str    e.g. "rice"
    location     str    e.g. "karnataka"
    area         float  hectares
    rainfall     float  mm/month average
    temperature  float  °C average
    soil_type    str    e.g. "loamy"

  Returns:
    {
      "crop":              str,
      "location":          str,
      "area_ha":           float,
      "yield_per_hectare": int,     # kg/ha
      "total_yield":       int,     # kg  (= yield_per_ha × area)
      "unit":              "kg",
      "confidence":        float,   # 0.70 – 0.95
      "confidence_pct":    str,     # e.g. "87%"
      "rating":            str,     # "Excellent" | "Good" | "Average" | "Below Average" | "Poor"
      "advice":            str,
      "breakdown": {
          "base_yield":          int,
          "rainfall_factor":     float,
          "temperature_factor":  float,
          "soil_factor":         float,
      }
    }
"""

from __future__ import annotations


# ── Base yields (kg / hectare under average conditions) ───────────────────────
_BASE_YIELD: dict[str, int] = {
    "rice":      5000,
    "wheat":     4000,
    "maize":     4500,
    "soybean":   2500,
    "groundnut": 2000,
    "cotton":    1500,   # seed-cotton
    "sugarcane": 70000,  # fresh cane
    "tomato":    25000,
    "onion":     20000,
    "potato":    22000,
    "coconut":   10000,  # nuts/ha × avg nut weight
    "arecanut":  2000,
    "coffee":     800,   # arabica / robusta average
    "pepper":     700,
    "turmeric":  6000,
    "ginger":    8000,
}
_DEFAULT_BASE = 3000


# ── Per-crop optimal rainfall (mm / month) ────────────────────────────────────
# (min_optimal, max_optimal)  — outside this band yield starts to drop
_RAIN_OPTIMAL: dict[str, tuple[float, float]] = {
    "rice":      (150, 300),
    "wheat":     ( 60, 120),
    "maize":     ( 80, 160),
    "soybean":   ( 80, 150),
    "groundnut": ( 60, 120),
    "cotton":    ( 60, 100),
    "sugarcane": (150, 250),
    "tomato":    ( 60, 100),
    "onion":     ( 50,  90),
    "potato":    ( 70, 120),
    "coconut":   (150, 250),
    "arecanut":  (150, 300),
    "coffee":    (150, 250),
    "pepper":    (150, 250),
    "turmeric":  (150, 250),
    "ginger":    (150, 250),
}
_DEFAULT_RAIN_OPT = (80, 160)


# ── Per-crop optimal temperature range (°C) ───────────────────────────────────
_TEMP_OPTIMAL: dict[str, tuple[float, float]] = {
    "rice":      (22, 32),
    "wheat":     (15, 24),
    "maize":     (21, 30),
    "soybean":   (20, 28),
    "groundnut": (24, 30),
    "cotton":    (25, 35),
    "sugarcane": (24, 34),
    "tomato":    (18, 27),
    "onion":     (15, 25),
    "potato":    (14, 22),
    "coconut":   (25, 35),
    "arecanut":  (22, 32),
    "coffee":    (18, 26),
    "pepper":    (20, 30),
    "turmeric":  (20, 30),
    "ginger":    (20, 30),
}
_DEFAULT_TEMP_OPT = (20, 30)


# ── Soil type yield multipliers ───────────────────────────────────────────────
_SOIL_FACTOR: dict[str, float] = {
    "loamy":        1.00,
    "alluvial":     1.00,
    "black":        0.95,   # "black cotton soil"
    "clay":         0.88,
    "sandy loam":   0.90,
    "red laterite": 0.82,
    "sandy":        0.75,
    "laterite":     0.80,
    "silty":        0.95,
    "peaty":        0.85,
}
_DEFAULT_SOIL_FACTOR = 0.90   # unknown soil type → conservative


# ── Advice templates ─────────────────────────────────────────────────────────
_ADVICE: dict[str, str] = {
    "Excellent":      "Excellent conditions — optimise by ensuring timely harvesting and post-harvest storage.",
    "Good":           "Good yield expected. Maintain current irrigation and fertilizer schedule.",
    "Average":        "Average yield likely. Consider foliar spray of micronutrients and check irrigation consistency.",
    "Below Average":  "Below-average yield risk. Improve soil health with organic matter and verify water availability.",
    "Poor":           "Poor yield risk. Consult an agronomist — consider crop insurance and remedial soil treatment.",
}


# ── Helper: factor from value vs optimal range ─────────────────────────────────
def _range_factor(value: float, low: float, high: float) -> tuple[float, float]:
    """
    Returns (factor, penalty):
      factor ∈ [0.60, 1.10]
      penalty ∈ [0.0, 0.15]  (subtracted from confidence)
    """
    if low <= value <= high:
        # In optimal zone — slight bonus for being in the middle
        mid = (low + high) / 2
        bonus = 0.10 * (1 - abs(value - mid) / ((high - low) / 2))
        return min(1.10, 1.0 + bonus * 0.5), 0.0

    # Below optimal
    if value < low:
        deficit = (low - value) / low
        factor  = max(0.60, 1.0 - deficit * 1.2)
        penalty = min(0.15, deficit * 0.20)
        return factor, penalty

    # Above optimal
    excess  = (value - high) / high
    factor  = max(0.60, 1.0 - excess * 1.0)
    penalty = min(0.15, excess * 0.15)
    return factor, penalty


def _safe_float(val, default: float) -> float:
    try:
        v = float(val)
        return v if v > 0 else default
    except Exception:
        return default


def _normalise_soil(soil: str) -> str:
    return (soil or "").strip().lower()


# ── Public function ───────────────────────────────────────────────────────────
def predict_yield(data: dict) -> dict:
    """
    Predict crop yield using rule-based factor analysis.
    Always returns a valid dict — never raises.
    """
    try:
        crop        = (data.get("crop") or "rice").strip().lower()
        location    = (data.get("location") or "karnataka").strip()
        area        = _safe_float(data.get("area"), 1.0)
        rainfall    = _safe_float(data.get("rainfall"), 120.0)
        temperature = _safe_float(data.get("temperature"), 26.0)
        soil_raw    = _normalise_soil(data.get("soil_type") or "loamy")

        base_yield = _BASE_YIELD.get(crop, _DEFAULT_BASE)

        # ── Rainfall factor ─────────────────────────────────────────────────
        rain_low, rain_high = _RAIN_OPTIMAL.get(crop, _DEFAULT_RAIN_OPT)
        rain_factor, rain_penalty = _range_factor(rainfall, rain_low, rain_high)

        # ── Temperature factor ──────────────────────────────────────────────
        temp_low, temp_high = _TEMP_OPTIMAL.get(crop, _DEFAULT_TEMP_OPT)
        temp_factor, temp_penalty = _range_factor(temperature, temp_low, temp_high)

        # ── Soil factor ─────────────────────────────────────────────────────
        # Match partial soil name (e.g. "red laterite soil" → "red laterite")
        soil_factor = _DEFAULT_SOIL_FACTOR
        soil_penalty = 0.05   # unknown soil gets small penalty
        for key, val in _SOIL_FACTOR.items():
            if key in soil_raw:
                soil_factor  = val
                soil_penalty = max(0.0, (1.0 - val) * 0.10)
                break

        # ── Combined prediction ─────────────────────────────────────────────
        yield_per_ha = int(base_yield * rain_factor * temp_factor * soil_factor)
        total_yield  = int(yield_per_ha * area)

        # ── Confidence ─────────────────────────────────────────────────────
        confidence = round(
            max(0.70, 0.95 - rain_penalty - temp_penalty - soil_penalty),
            2,
        )

        # ── Rating ─────────────────────────────────────────────────────────
        ratio = yield_per_ha / base_yield
        if   ratio >= 1.08: rating = "Excellent"
        elif ratio >= 0.92: rating = "Good"
        elif ratio >= 0.78: rating = "Average"
        elif ratio >= 0.62: rating = "Below Average"
        else:               rating = "Poor"

        advice = _ADVICE[rating]

        # ── Specific tips based on stress factors ───────────────────────────
        tips = []
        if rain_factor < 0.85:
            if rainfall < rain_low:
                tips.append(f"Irrigation recommended — rainfall ({rainfall:.0f} mm) is below optimum for {crop}.")
            else:
                tips.append(f"Drainage management needed — excess rainfall may waterlog roots.")
        if temp_factor < 0.85:
            if temperature < temp_low:
                tips.append(f"Temperature ({temperature:.0f}°C) is cooler than optimal — consider shade nets for cold nights.")
            else:
                tips.append(f"Temperature ({temperature:.0f}°C) is high — ensure adequate irrigation and mulching.")
        if soil_factor < 0.85:
            tips.append("Soil improvement with organic compost or green manure will significantly boost yield.")

        if tips:
            advice = advice + " " + " ".join(tips)

        return {
            "crop":              crop.capitalize(),
            "location":          location,
            "area_ha":           area,
            "yield_per_hectare": yield_per_ha,
            "total_yield":       total_yield,
            "unit":              "kg",
            "confidence":        confidence,
            "confidence_pct":    f"{int(confidence * 100)}%",
            "rating":            rating,
            "advice":            advice,
            "breakdown": {
                "base_yield":         base_yield,
                "rainfall_factor":    round(rain_factor, 3),
                "temperature_factor": round(temp_factor, 3),
                "soil_factor":        round(soil_factor, 3),
            },
        }

    except Exception as exc:
        # Hard fallback — always return something valid
        print(f"[YieldService] Error: {exc}")
        return {
            "crop":              str(data.get("crop", "crop")).capitalize(),
            "location":          str(data.get("location", "")),
            "area_ha":           1.0,
            "yield_per_hectare": 3000,
            "total_yield":       3000,
            "unit":              "kg",
            "confidence":        0.70,
            "confidence_pct":    "70%",
            "rating":            "Average",
            "advice":            "Could not compute detailed prediction. Using default estimates.",
            "breakdown": {
                "base_yield": 3000,
                "rainfall_factor": 1.0,
                "temperature_factor": 1.0,
                "soil_factor": 1.0,
            },
        }

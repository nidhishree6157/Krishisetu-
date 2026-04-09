"""
recommendation_service.py
─────────────────────────
Unified intelligent crop recommendation pipeline.

Modes
─────
  existing  →  user already grows a crop; return fertilizer advice only.
  new       →  full ML pipeline:
                 1. Fetch live weather for the supplied location.
                 2. Build feature vector (soil + weather).
                 3. Get top-3 crops via predict_proba().
                 4. Apply simple location-based priority boost.
                 5. Return top-3 list + legacy "crop" field.

Backward Compatibility
──────────────────────
  • Response always includes "crop" (top-1 name).
  • All previously returned keys are still present.
  • DB save in recommendation.py route is unaffected.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


# ──────────────────────────────────────────────────────────────
# CLIMATE MODEL  (4-feature companion model)
# Trained on crop_dataset.csv via models/train_crop_model.py.
# Features: temperature, humidity, rainfall, ph
# Complements the primary 7-feature model in routes/ai.py by
# providing a climate-only signal — useful for plantation crops
# where soil NPK is less discriminating than agro-climate profile.
# ──────────────────────────────────────────────────────────────
_CLIMATE_MODEL_PATH = (
    Path(__file__).resolve().parents[1] / "models" / "crop_model.pkl"
)
_climate_model = None          # loaded lazily on first use


def _load_climate_model():
    """
    Lazy-load the 4-feature climate model.  Returns None (silently) if
    the model file is absent so the pipeline degrades gracefully.
    """
    global _climate_model
    if _climate_model is not None:
        return _climate_model
    try:
        import joblib
        _climate_model = joblib.load(_CLIMATE_MODEL_PATH)
        print(
            f"[ClimateModel] Loaded {_CLIMATE_MODEL_PATH.name} "
            f"({len(_climate_model.classes_)} classes)"
        )
    except FileNotFoundError:
        print(
            "[ClimateModel] crop_model.pkl not found — "
            "run  python models/train_crop_model.py  to generate it."
        )
    except Exception as exc:
        print(f"[ClimateModel] Load failed: {exc}")
    return _climate_model


def _climate_predict(
    temperature: float,
    humidity:    float,
    rainfall:    float,
    ph:          float,
) -> list[dict]:
    """
    Run the 4-feature climate model and return a ranked list of dicts:
      [{"name": str, "confidence": int}, ...]

    Returns an empty list if the model is unavailable or errors.
    """
    model = _load_climate_model()
    if model is None:
        return []
    try:
        X     = np.array([[temperature, humidity, rainfall, ph]], dtype=float)
        proba = model.predict_proba(X)[0]
        prob_map = {str(cls): float(p) for cls, p in zip(model.classes_, proba)}
        ranked = sorted(prob_map.items(), key=lambda kv: kv[1], reverse=True)
        return [
            {"name": name, "confidence": round(prob * 100)}
            for name, prob in ranked
            if prob > 0.05   # skip negligible classes
        ]
    except Exception as exc:
        print(f"[ClimateModel] Prediction failed: {exc}")
        return []


# ──────────────────────────────────────────────────────────────
# LOCATION -> PREFERRED CROPS  (simple rule-based map)
# Keys are lowercase fragments to match anywhere in the location
# string.  Values are crops whose probability score gets a small
# additive boost so they surface higher in the ranking.
# ──────────────────────────────────────────────────────────────
_LOCATION_BOOSTS: dict[str, list[str]] = {
    # Field / grain crops
    "karnataka":     ["rice", "ragi", "maize", "sugarcane", "coffee", "arecanut", "pepper", "cotton"],
    "punjab":        ["wheat", "rice", "maize", "cotton"],
    "maharashtra":   ["soybean", "cotton", "sugarcane", "jowar", "wheat"],
    "tamil nadu":    ["rice", "banana", "groundnut", "sugarcane", "coconut", "coffee"],
    "tamilnadu":     ["rice", "banana", "groundnut", "sugarcane", "coconut", "coffee"],
    "andhra":        ["rice", "chilli", "cotton", "groundnut", "coconut"],
    "telangana":     ["cotton", "rice", "maize", "sugarcane"],
    "uttar pradesh": ["wheat", "sugarcane", "potato", "rice"],
    "up":            ["wheat", "sugarcane", "potato", "rice"],
    "rajasthan":     ["bajra", "wheat", "mustard", "jowar"],
    "bihar":         ["rice", "wheat", "maize", "sugarcane"],
    "gujarat":       ["cotton", "groundnut", "wheat", "bajra", "coconut"],
    "madhya pradesh":["soybean", "wheat", "maize", "cotton"],
    "mp":            ["soybean", "wheat", "maize", "cotton"],
    "west bengal":   ["rice", "jute", "potato", "maize", "coconut"],
    "haryana":       ["wheat", "rice", "sugarcane", "cotton"],
    "odisha":        ["rice", "groundnut", "maize", "coconut"],
    "assam":         ["rice", "tea", "jute", "sugarcane", "arecanut", "pepper"],
    "jharkhand":     ["rice", "maize", "wheat"],
    "chhattisgarh":  ["rice", "maize", "soybean"],
    # Plantation crop regions
    "kerala":        ["coconut", "pepper", "arecanut", "coffee", "rice", "banana", "tapioca"],
    "goa":           ["coconut", "arecanut", "pepper", "rice"],
    "coorg":         ["coffee", "pepper", "arecanut", "rice"],
    "kodagu":        ["coffee", "pepper", "arecanut", "rice"],
    "wayanad":       ["coffee", "pepper", "arecanut", "rice"],
    "chikmagalur":   ["coffee", "arecanut", "rice"],
    "shimoga":       ["arecanut", "paddy", "rice"],
    "uttara kannada":["arecanut", "coconut", "pepper"],
    "dakshina kannada":["arecanut", "coconut", "pepper", "rice"],
    "udupi":         ["arecanut", "coconut", "pepper", "rice"],
    "meghalaya":     ["pepper", "arecanut", "rice"],
    "mizoram":       ["arecanut", "rice"],
    "manipur":       ["arecanut", "rice"],
    "nagaland":      ["arecanut", "rice", "maize"],
    "tripura":       ["arecanut", "rice", "jute"],
}

# Probability points added to boosted crops (0.0 – 1.0 scale)
_BOOST_DELTA = 0.08


# ──────────────────────────────────────────────────────────────
# DEFAULTS used when weather API is unavailable or location is
# missing.  These match the training-data medians in ai.py so
# predictions remain sensible.
# ──────────────────────────────────────────────────────────────
_DEFAULT_WEATHER = {
    "temperature": 25.0,
    "humidity":    60.0,
    "rainfall":    100.0,   # mm (approximate monthly equivalent)
}


# ──────────────────────────────────────────────────────────────
# SAFE VALUE HELPER
# Converts any value to float and validates it against a
# domain-specific range.  Returns *default* when the value is
# missing, non-numeric, or out of the valid range.
#
#   temperature : 1 – 55 °C   (Indian agriculture range)
#   humidity    : 1 – 100 %
#   rainfall    : 0 – 500 mm  (monthly equivalent)
#   ph          : 3 – 10      (agronomically meaningful)
# ──────────────────────────────────────────────────────────────
def _safe_val(val, default: float, lo: float = 0.0, hi: float = float("inf")) -> float:
    try:
        v = float(val)
        if v < lo or v > hi:
            return default
        return v
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────
# WEATHER HELPER
# ──────────────────────────────────────────────────────────────
def _get_weather_for_location(location: str | None) -> dict:
    """
    Attempt to fetch live weather for *location*.
    Returns a dict with guaranteed numeric keys
    (temperature, humidity, rainfall).

    rainfall from _fetch_weather is in mm/hour (1h observation).
    We multiply by 24 * 30 to approximate monthly rainfall so it
    sits in the same scale the ML model was trained on.  When the
    API doesn't return rain data we fall back to the default.
    """
    weather = {"source": "default", **_DEFAULT_WEATHER}

    city = str(location or "").strip()
    if not city:
        return weather

    try:
        from routes.weather import _fetch_weather   # local import avoids circular deps at module load
        raw = _fetch_weather(city)

        temp = raw.get("temperature")
        hum  = raw.get("humidity")
        rain = raw.get("rainfall")   # mm/h or None

        if temp is not None:
            weather["temperature"] = _safe_val(temp, _DEFAULT_WEATHER["temperature"], lo=1.0, hi=55.0)
        if hum is not None:
            weather["humidity"] = _safe_val(hum, _DEFAULT_WEATHER["humidity"], lo=1.0, hi=100.0)
        if rain is not None:
            # Convert hourly precipitation to approximate monthly (720 h/month).
            # When current hourly rain is 0 (e.g. dry day in a normally wet
            # region), fall back to the seasonal default so crop recommendation
            # uses climatologically meaningful rainfall rather than 0 mm.
            hourly = _safe_val(rain, 0.0, lo=0.0, hi=500.0)
            if hourly > 0.0:
                weather["rainfall"] = min(hourly * 720, 400.0)
            # else: keep the seasonal default already in weather["rainfall"]

        weather["source"] = raw.get("source", "api")
        weather["condition"] = raw.get("condition", "Unknown")

    except Exception as exc:
        print(f"[WeatherFetch] Failed for '{city}': {exc} — using defaults")

    return weather


# ──────────────────────────────────────────────────────────────
# LOCATION BOOST
# ──────────────────────────────────────────────────────────────
def _apply_location_boost(
    prob_map: dict[str, float],
    location: str | None,
) -> dict[str, float]:
    """
    Add a small probability bonus to regionally appropriate crops.
    Does not renormalise — we only need relative ordering.
    """
    if not location:
        return prob_map

    loc_lower = location.lower()
    boosted = dict(prob_map)

    for keyword, crops in _LOCATION_BOOSTS.items():
        if keyword in loc_lower:
            for crop in crops:
                crop_lower = crop.lower()
                # Match case-insensitively against existing keys
                for key in list(boosted.keys()):
                    if key.lower() == crop_lower:
                        boosted[key] = boosted[key] + _BOOST_DELTA
            break   # one region match is enough

    return boosted


# ──────────────────────────────────────────────────────────────
# PLANTATION CROP INJECTION
# When the ML top-1 crop has low confidence AND rule-based logic
# strongly identifies a plantation crop, the plantation crop is
# prepended to the top-3 list so it is always visible to the user.
# The existing ML results are kept (shifted down) for transparency.
# ──────────────────────────────────────────────────────────────
_PLANTATION_CONF_THRESHOLD = 40    # % — inject when ML top-1 is below this


def _inject_plantation_crops(
    top3:     list[dict],
    data:     dict,
    location: str | None,
) -> list[dict]:
    """
    Evaluate rule-based plantation crop logic and merge results into *top3*.

    Rules:
      • If ML top-1 confidence < threshold → prepend the best rule-based
        plantation crop (if one matches) and trim list to 3.
      • If location explicitly mentions a plantation region → boost that
        crop regardless of ML confidence, but only if it's not already
        in the top-3.
      • Returns unmodified *top3* when no plantation crop qualifies.
    """
    try:
        from routes.ai import fallback_crop_logic

        rule_crop = fallback_crop_logic(data)
        if not rule_crop:
            return top3

        # Already in top-3? Nothing to do.
        existing_names = {c["name"].lower() for c in top3}
        if rule_crop.lower() in existing_names:
            return top3

        top1_conf = top3[0]["confidence"] if top3 else 0
        loc_lower = (location or "").lower()

        # Plantation region keywords — city/district names that are
        # strongly associated with arecanut/coconut/coffee/pepper.
        plantation_regions = {
            # States / broad regions
            "kerala", "goa", "assam", "meghalaya", "mizoram",
            "manipur", "nagaland", "tripura",
            # Karnataka plantation districts
            "coorg", "kodagu", "wayanad", "chikmagalur", "shimoga",
            "udupi", "dakshina kannada", "uttara kannada",
            # Cities / towns in plantation belts
            "mangalore", "mangaluru", "kasaragod", "thrissur",
            "kozhikode", "kannur", "malappuram", "palakkad",
            "kochi", "ernakulam", "alappuzha", "pathanamthitta",
            "sakleshpur", "mudigere", "somwarpet", "madikeri",
            "sirsi", "siddapur", "ankola",
        }
        in_plantation_region = any(r in loc_lower for r in plantation_regions)

        should_inject = top1_conf < _PLANTATION_CONF_THRESHOLD or in_plantation_region

        if should_inject:
            # Confidence for the rule-based entry: match or just beat ML top-1
            rule_conf = max(top1_conf + 5, 60)
            injected  = {"name": rule_crop, "confidence": rule_conf}
            # Prepend and keep top-3
            merged    = [injected] + top3
            merged    = merged[:3]
            print(
                f"[Recommendation] Plantation injection: '{rule_crop}' "
                f"(conf={rule_conf}%) — ML top1_conf={top1_conf}% "
                f"plantation_region={in_plantation_region}"
            )
            return merged

    except Exception as exc:
        print(f"[Recommendation] Plantation injection failed: {exc}")

    return top3


# ──────────────────────────────────────────────────────────────
# TOP-3 EXTRACTOR
# ──────────────────────────────────────────────────────────────
def _get_top3(model, X: np.ndarray, location: str | None) -> list[dict]:
    """
    Use predict_proba() to build a ranked list of up to 3 crops.
    Falls back to predict() if the model doesn't support proba.
    Returns:
        [{"name": str, "confidence": int}, ...]   (confidence 0-100)
    """
    try:
        proba = model.predict_proba(X)[0]          # shape: (n_classes,)
        classes = model.classes_                   # aligned array of crop names

        prob_map = {str(cls): float(p) for cls, p in zip(classes, proba)}
        prob_map = _apply_location_boost(prob_map, location)

        sorted_crops = sorted(prob_map.items(), key=lambda kv: kv[1], reverse=True)
        top3 = [
            {
                "name":       name,
                "confidence": round(prob * 100),
            }
            for name, prob in sorted_crops[:3]
            if prob > 0
        ]
        return top3

    except Exception as exc:
        print(f"[Top3] predict_proba failed: {exc} — falling back to predict()")
        pred = str(model.predict(X)[0])
        return [{"name": pred, "confidence": 100}]


# ──────────────────────────────────────────────────────────────
# CROP KNOWLEDGE BASE — used by _build_explanation()
# ──────────────────────────────────────────────────────────────
_CROP_CONTEXT: dict[str, dict] = {
    "coffee": {
        "opt_temp":   "18–26°C",
        "opt_rain":   "100–220 mm",
        "opt_humid":  "65–85%",
        "temp_lo": 18.0, "temp_hi": 26.0,
        "soil_pref":  "slightly acidic (pH 5.5–7.0), well-drained loam",
        "driver":     "cool temperature with consistent, moderate rainfall",
        "regions":    "Coorg, Chikmagalur, Wayanad, Nilgiris",
    },
    "arecanut": {
        "opt_temp":   "20–32°C",
        "opt_rain":   "> 180 mm",
        "opt_humid":  "≥ 80%",
        "temp_lo": 20.0, "temp_hi": 32.0,
        "soil_pref":  "well-drained loamy to red laterite, pH 6.0–7.0",
        "driver":     "very high humidity (≥ 80%) and heavy rainfall",
        "regions":    "coastal Karnataka, Assam, Kerala, North-East India",
    },
    "pepper": {
        "opt_temp":   "20–32°C",
        "opt_rain":   "120–220 mm",
        "opt_humid":  "> 75%",
        "temp_lo": 20.0, "temp_hi": 32.0,
        "soil_pref":  "well-drained acidic soil (pH 5.5–6.8), rich organic matter",
        "driver":     "high humidity, partial shade conditions, and acidic soil",
        "regions":    "Kerala, Goa, coastal Karnataka, Malabar region",
    },
    "coconut": {
        "opt_temp":   "22–35°C",
        "opt_rain":   "> 80 mm",
        "opt_humid":  "> 68%",
        "temp_lo": 22.0, "temp_hi": 35.0,
        "soil_pref":  "sandy loam to clay loam, wide pH tolerance (5.2–8.0)",
        "driver":     "warm tropical climate with moderate-to-high humidity",
        "regions":    "Kerala, Tamil Nadu, Karnataka coast, Andhra Pradesh, Goa",
    },
    "rice": {
        "opt_temp":   "22–32°C",
        "opt_rain":   "150–250 mm",
        "opt_humid":  "> 75%",
        "temp_lo": 22.0, "temp_hi": 32.0,
        "soil_pref":  "clay to loamy, high water retention, nitrogen-rich (pH 5.5–7.0)",
        "driver":     "high humidity, substantial rainfall, and nitrogen-rich soil",
        "regions":    "Andhra Pradesh, West Bengal, Punjab, Odisha, Kerala",
    },
    "wheat": {
        "opt_temp":   "14–22°C",
        "opt_rain":   "50–100 mm",
        "opt_humid":  "45–65%",
        "temp_lo": 14.0, "temp_hi": 22.0,
        "soil_pref":  "well-drained loamy, moderate NPK (pH 6.0–7.5)",
        "driver":     "cool temperature and moderate rainfall during grain fill",
        "regions":    "Punjab, Haryana, Uttar Pradesh, MP, Rajasthan",
    },
    "maize": {
        "opt_temp":   "20–30°C",
        "opt_rain":   "80–140 mm",
        "opt_humid":  "55–75%",
        "temp_lo": 20.0, "temp_hi": 30.0,
        "soil_pref":  "well-drained loamy, moderate potassium (pH 5.8–7.0)",
        "driver":     "moderate temperature, balanced humidity, and good drainage",
        "regions":    "Karnataka, Andhra Pradesh, Bihar, MP, Rajasthan",
    },
    "cotton": {
        "opt_temp":   "25–35°C",
        "opt_rain":   "40–80 mm",
        "opt_humid":  "40–60%",
        "temp_lo": 25.0, "temp_hi": 35.0,
        "soil_pref":  "black soil or sandy loam, slightly alkaline (pH 6.5–8.0)",
        "driver":     "warm, drier climate and alkaline well-drained soil",
        "regions":    "Maharashtra, Gujarat, Telangana, Karnataka, Punjab",
    },
    "sugarcane": {
        "opt_temp":   "26–33°C",
        "opt_rain":   "100–200 mm",
        "opt_humid":  "70–90%",
        "temp_lo": 26.0, "temp_hi": 33.0,
        "soil_pref":  "deep loamy, high nitrogen and potassium (pH 6.0–7.5)",
        "driver":     "warm climate, high soil potassium, and consistent moisture",
        "regions":    "Uttar Pradesh, Maharashtra, Karnataka, Tamil Nadu, Bihar",
    },
    "soybean": {
        "opt_temp":   "20–30°C",
        "opt_rain":   "80–120 mm",
        "opt_humid":  "55–75%",
        "temp_lo": 20.0, "temp_hi": 30.0,
        "soil_pref":  "well-drained loamy, moderate fertility (pH 6.0–7.0)",
        "driver":     "moderate temperature and balanced soil nutrients",
        "regions":    "Madhya Pradesh, Maharashtra, Rajasthan, Karnataka",
    },
    "groundnut": {
        "opt_temp":   "25–35°C",
        "opt_rain":   "60–100 mm",
        "opt_humid":  "50–70%",
        "temp_lo": 25.0, "temp_hi": 35.0,
        "soil_pref":  "sandy loam, well-drained, calcium-rich (pH 6.0–7.5)",
        "driver":     "warm climate and well-drained sandy soil",
        "regions":    "Gujarat, Andhra Pradesh, Tamil Nadu, Karnataka, Rajasthan",
    },
}


def _build_explanation(
    crop: str,
    mode: str,
    nitrogen: float,
    phosphorus: float,
    potassium: float,
    ph: float,
    temperature: float,
    humidity: float,
    rainfall: float,
    location: str | None,
    confidence: int = 80,
    alternatives: list[str] | None = None,
) -> str:
    """
    Generate a human-readable, AI-style explanation for a crop recommendation.
    Covers climate fit, soil profile, regional context, and alternatives.
    """
    crop_key = crop.lower()
    ctx      = _CROP_CONTEXT.get(crop_key, {})
    loc_part = f" in {location}" if location else ""

    # ── EXISTING MODE — advice for a known crop ───────────────────────────────
    if mode == "existing":
        lines: list[str] = [
            f"You are currently growing {crop}{loc_part}.",
            f"Live conditions: temperature {temperature:.1f}°C, "
            f"humidity {humidity:.0f}%, rainfall {rainfall:.0f} mm.",
        ]
        if ctx:
            temp_lo = ctx.get("temp_lo", 10.0)
            temp_hi = ctx.get("temp_hi", 45.0)
            temp_status = (
                "well within the optimal range"
                if temp_lo <= temperature <= temp_hi
                else "slightly outside the ideal range — monitor for stress"
            )
            lines.append(
                f"Temperature is {temp_status} for {crop} "
                f"(optimal {ctx['opt_temp']}). "
                f"Seed varieties and fertilizer advice below have been "
                f"tailored to current weather conditions."
            )
        return "  ".join(lines)

    # ── NEW MODE — full reasoning ─────────────────────────────────────────────
    paras: list[str] = []

    # 1. Headline
    paras.append(
        f"Based on your farm inputs{loc_part}, {crop} is the top recommendation "
        f"with {confidence}% confidence."
    )

    # 2. Climate fit
    if ctx:
        temp_lo = ctx.get("temp_lo", 10.0)
        temp_hi = ctx.get("temp_hi", 45.0)
        temp_fit = (
            "ideal"
            if temp_lo + 2 <= temperature <= temp_hi - 2
            else "within an acceptable range"
        )
        rain_fit = "adequate" if rainfall >= 80 else "limited but manageable"
        hum_fit  = "supports" if humidity >= 60 else "is slightly below optimal for"

        climate_parts = [
            f"temperature ({temperature:.1f}°C) is {temp_fit} for {crop} "
            f"(optimal {ctx['opt_temp']})",
            f"rainfall ({rainfall:.0f} mm) is {rain_fit} "
            f"(optimal {ctx['opt_rain']})",
            f"humidity ({humidity:.0f}%) {hum_fit} {crop} growth "
            f"(optimal {ctx['opt_humid']})",
        ]
        paras.append("Climate fit: " + "; ".join(climate_parts) + ".")

    # 3. Soil profile
    soil_pref = ctx.get("soil_pref", "moderate fertility, well-drained soil")
    paras.append(
        f"Soil profile — Nitrogen {nitrogen:.0f}, Phosphorus {phosphorus:.0f}, "
        f"Potassium {potassium:.0f}, pH {ph:.1f} — is compatible with "
        f"{crop}'s requirement for {soil_pref}."
    )

    # 4. Primary driver
    if ctx.get("driver"):
        paras.append(
            f"Primary selection driver: {ctx['driver']}."
        )

    # 5. Regional benchmark
    if ctx.get("regions"):
        paras.append(
            f"{crop} is a proven crop in {ctx['regions']}, "
            f"which share a similar agro-climatic profile to your inputs."
        )

    # 6. Alternatives
    if alternatives:
        alt_list = [a for a in alternatives[:3] if a.lower() != crop_key][:2]
        if alt_list:
            paras.append(
                f"Also consider: {', '.join(alt_list)} — these crops suit "
                f"your conditions and may be viable alternatives depending "
                f"on market preference."
            )

    return "\n\n".join(paras)


# ──────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────
def full_recommendation(data: dict) -> dict:
    """
    Entry point called by POST /api/recommend.

    Returns a dict that is safe to serialise as JSON and is
    backward-compatible with the previous schema:
      crop          – top-1 crop name  (legacy field, always present)
      fertilizer    – fertilizer string
      seeds         – list or []
      location      – echoed back
      mode          – echoed back
      recommended_crops – [{"name", "confidence"}, ...]  (new field)
      weather       – weather dict used for inference    (new field)
    """
    try:
        from routes.ai import _FEATURES, load_or_train_model
        from routes.fertilizer import get_fertilizer_recommendation
        from services.seed_service import get_seed_recommendation

        mode     = str(data.get("mode") or "").strip().lower()
        location = str(data.get("location") or "").strip() or None
        crop     = data.get("crop")

        # ── EXISTING MODE ──────────────────────────────────────
        if mode == "existing":
            crop = str(crop or "rice")

            def _ef(key: str, default: float) -> float:
                v = data.get(key)
                try:
                    return float(v) if v is not None else default
                except (TypeError, ValueError):
                    return default

            ex_n = _ef("nitrogen", 0.0)
            ex_p = _ef("phosphorus", 0.0)
            ex_k = _ef("potassium", 0.0)
            raw_ex_ph = _ef("ph", _ef("soil_ph", 7.0))
            ex_ph = raw_ex_ph if 3.0 <= raw_ex_ph <= 10.0 else 7.0

            fertilizer = get_fertilizer_recommendation(crop)
            weather_info = _get_weather_for_location(location)
            temperature = _safe_val(weather_info["temperature"], 25.0, lo=1.0, hi=55.0)
            humidity    = _safe_val(weather_info["humidity"],    60.0, lo=1.0, hi=100.0)
            rainfall    = _safe_val(weather_info["rainfall"],   100.0, lo=0.0, hi=400.0)
            seed_recs: list[dict] = []
            try:
                seed_recs = get_seed_recommendation(
                    crop,
                    location=location,
                    weather={
                        "temperature": temperature,
                        "humidity":    humidity,
                        "rainfall":    rainfall,
                    },
                ) or []
            except Exception as seed_exc:
                print(f"[Recommendation] Seed service failed (existing mode): {seed_exc}")
            seeds = [s["name"] for s in seed_recs]
            explanation = _build_explanation(
                crop=crop, mode=mode,
                nitrogen=ex_n, phosphorus=ex_p, potassium=ex_k, ph=ex_ph,
                temperature=temperature, humidity=humidity, rainfall=rainfall,
                location=location, confidence=100, alternatives=None,
            )
            return {
                "success":              True,
                "crop":                 crop,
                "seeds":                seeds,
                "fertilizer":           str(fertilizer),
                "seed_recommendations": seed_recs,
                "explanation":          explanation,
                "location":             location,
                "mode":                 mode,
                "recommended_crops":    [{"name": crop, "confidence": 100}],
                "weather": {
                    "temperature": temperature,
                    "humidity":    humidity,
                    "rainfall":    rainfall,
                    "condition":   weather_info.get("condition", "Unknown"),
                    "source":      weather_info.get("source", "default"),
                },
            }

        # ── NEW MODE ───────────────────────────────────────────
        if mode == "new":

            # 1. Fetch live weather (safe — uses defaults on failure)
            weather_info = _get_weather_for_location(location)

            # Secondary clamp: guard against any edge case that slipped
            # through _get_weather_for_location (e.g. manually supplied values).
            temperature = _safe_val(weather_info["temperature"], 25.0, lo=1.0, hi=55.0)
            humidity    = _safe_val(weather_info["humidity"],    60.0, lo=1.0, hi=100.0)
            rainfall    = _safe_val(weather_info["rainfall"],   100.0, lo=0.0, hi=400.0)
            print("Weather Used:", temperature, humidity, rainfall,
                  "| source:", weather_info.get("source", "default"),
                  "| location:", location)

            # 2. Build feature vector
            #    Feature order MUST match _FEATURES in routes/ai.py:
            #    [nitrogen, phosphorus, potassium, temperature, humidity, ph, rainfall]
            def _fval(key: str, default: float) -> float:
                v = data.get(key)
                try:
                    return float(v) if v is not None else default
                except (TypeError, ValueError):
                    return default

            # pH accepted as "ph" or "soil_ph"; clamped to agronomic range 3–10.
            raw_ph = _fval("ph", _fval("soil_ph", 6.5))
            ph = raw_ph if 3.0 <= raw_ph <= 10.0 else 7.0

            features = np.array([[
                _fval("nitrogen",   90.0),   # index 0
                _fval("phosphorus", 40.0),   # index 1
                _fval("potassium",  40.0),   # index 2
                temperature,                 # index 3
                humidity,                    # index 4
                ph,                          # index 5
                rainfall,                    # index 6
            ]], dtype=float)

            # 3. Predict — isolated try/except so a model failure always
            #    returns a graceful fallback instead of a 500 error.
            try:
                model = load_or_train_model()
                top3  = _get_top3(model, features, location)
                if not top3:
                    raise ValueError("Empty top-3 result")
            except Exception as model_exc:
                print(f"[Recommendation] Model failed: {model_exc} — using fail-safe")
                top3 = [{"name": "Rice", "confidence": 80}]

            # 4. Climate model blending
            #    Run the 4-feature companion model (trained on crop_dataset.csv).
            #    Blend its output with the primary 7-feature model's top-3 by
            #    adding a weighted signal to each crop's probability.
            #
            #    Weight design:
            #      • Primary  model (7 features, soil+climate) : 70 %
            #      • Climate  model (4 features, climate-only) : 30 %
            #    This prevents the climate model from overriding a high-confidence
            #    soil-based result while still letting it surface plantation crops
            #    that the primary model may under-rank.
            climate_top = _climate_predict(temperature, humidity, rainfall, ph)
            if climate_top:
                _W_PRIMARY  = 0.70
                _W_CLIMATE  = 0.30

                # Build a unified score map from the 7-feature model
                score_map: dict[str, float] = {
                    c["name"]: c["confidence"] * _W_PRIMARY for c in top3
                }
                # Blend in climate model scores
                for item in climate_top:
                    name = item["name"]
                    score_map[name] = (
                        score_map.get(name, 0.0) + item["confidence"] * _W_CLIMATE
                    )

                # Re-rank by blended score and rebuild top-3
                blended = sorted(score_map.items(), key=lambda kv: kv[1], reverse=True)
                top3 = [
                    {"name": name, "confidence": min(round(score), 100)}
                    for name, score in blended[:3]
                ]
                print(
                    f"[ClimateModel] Blended top-3: "
                    + ", ".join(f"{c['name']}({c['confidence']}%)" for c in top3)
                )

            # 5. Inject plantation crops when conditions match and ML is uncertain
            top3 = _inject_plantation_crops(
                top3,
                {
                    "temperature": temperature,
                    "humidity":    humidity,
                    "rainfall":    rainfall,
                    "ph":          ph,
                },
                location,
            )

            top_crop   = top3[0]["name"] if top3 else "Rice"
            fertilizer = get_fertilizer_recommendation(top_crop)

            seed_recs: list[dict] = []
            try:
                seed_recs = get_seed_recommendation(
                    top_crop,
                    location=location,
                    weather={
                        "temperature": temperature,
                        "humidity":    humidity,
                        "rainfall":    rainfall,
                    },
                ) or []
            except Exception as seed_exc:
                print(f"[Recommendation] Seed service failed: {seed_exc}")

            # Legacy flat list of names (frontend still uses seeds[i] as string)
            seeds = [s["name"] for s in seed_recs]

            top1_confidence = top3[0]["confidence"] if top3 else 80
            alt_names = [c["name"] for c in top3[1:]]
            explanation = _build_explanation(
                crop=top_crop, mode=mode,
                nitrogen=_fval("nitrogen", 90.0),
                phosphorus=_fval("phosphorus", 40.0),
                potassium=_fval("potassium", 40.0),
                ph=ph,
                temperature=temperature,
                humidity=humidity,
                rainfall=rainfall,
                location=location,
                confidence=top1_confidence,
                alternatives=alt_names,
            )

            return {
                "success":              True,
                "crop":                 top_crop,           # legacy — top-1 name
                "recommended_crops":    top3,               # new — ranked list
                "fertilizer":           str(fertilizer),
                "seeds":                seeds,              # legacy — name strings
                "seed_recommendations": seed_recs,          # new — rich dicts
                "explanation":          explanation,        # new — AI reasoning
                "location":             location,
                "mode":                 mode,
                "weather": {
                    "temperature": temperature,
                    "humidity":    humidity,
                    "rainfall":    rainfall,
                    "condition":   weather_info.get("condition", "Unknown"),
                    "source":      weather_info.get("source", "default"),
                },
            }

        # ── UNKNOWN MODE ───────────────────────────────────────
        return {"success": False, "message": "Invalid mode. Use 'existing' or 'new'."}

    except Exception as exc:
        print(f"[full_recommendation] Unhandled error: {exc}")
        return {"success": False, "message": "Server error during recommendation"}


# ──────────────────────────────────────────────────────────────────────────────
# SIMPLE DIRECT CROP RECOMMENDATION
# ──────────────────────────────────────────────────────────────────────────────
# Uses crop_recommendation_model.pkl (7-feature sklearn model) directly.
# Direct PKL path (unused by /api/recommend; kept for tests or future use).
# The full weather-enriched pipeline (full_recommendation) is unaffected.
# ──────────────────────────────────────────────────────────────────────────────

_PKL_PATH = Path(__file__).resolve().parents[1] / "models" / "crop_recommendation_model.pkl"
_pkl_model = None          # lazy-loaded singleton


def _load_pkl_model():
    """
    Load crop_recommendation_model.pkl exactly once per process.
    Returns None (with a console warning) if the file is missing.
    """
    global _pkl_model
    if _pkl_model is not None:
        return _pkl_model
    try:
        import joblib
        _pkl_model = joblib.load(_PKL_PATH)
        print(
            f"[CropRecommend] Model loaded from {_PKL_PATH.name}  "
            f"classes={list(_pkl_model.classes_)}"
        )
    except FileNotFoundError:
        print(
            f"[CropRecommend] Model file not found: {_PKL_PATH}\n"
            "  Run  python models/train_crop_model.py  to create it."
        )
    except Exception as exc:
        print(f"[CropRecommend] Model load failed: {exc}")
    return _pkl_model


def get_crop_recommendation(data: dict) -> dict:
    """
    Direct 7-feature crop recommendation.

    Accepts keys using EITHER frontend naming (nitrogen / phosphorus / potassium)
    OR the N / P / K shorthand so callers can use whichever is convenient.

    Feature order must match training:
        [nitrogen, phosphorus, potassium, temperature, humidity, ph, rainfall]

    Returns:
        {
            "success":           bool,
            "recommended_crop":  str,           # top-1 crop name
            "recommended_crops": [              # top-3 with confidence
                {"name": str, "confidence": int}, ...
            ]
        }
    Always returns a result — never raises.
    """
    def _fv(primary: str, alias: str | None = None, default: float = 0.0) -> float:
        """Extract a float from data, trying primary then alias key."""
        for key in (primary, alias):
            if key is None:
                continue
            v = data.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return default

    # Build feature vector — order MUST match _FEATURES in routes/ai.py
    features = [
        _fv("nitrogen",    "N",  90.0),     # index 0
        _fv("phosphorus",  "P",  40.0),     # index 1
        _fv("potassium",   "K",  40.0),     # index 2
        _fv("temperature", None, 25.0),     # index 3
        _fv("humidity",    None, 60.0),     # index 4
        _fv("ph",          None,  6.5),     # index 5
        _fv("rainfall",    None,100.0),     # index 6
    ]

    print("[CropRecommend] INPUT:   ", data)
    print("[CropRecommend] FEATURES:", features)

    model = _load_pkl_model()
    if model is None:
        return {
            "success":           False,
            "recommended_crop":  "Rice",
            "recommended_crops": [{"name": "Rice", "confidence": 80}],
            "error":             "Model unavailable — using safe default",
        }

    try:
        prediction = str(model.predict([features])[0])
        print("[CropRecommend] PREDICTION:", prediction)

        # Build top-3 confidence list via predict_proba when available
        recommended_crops: list[dict] = []
        try:
            proba   = model.predict_proba([features])[0]
            classes = model.classes_
            pairs   = sorted(zip(classes, proba), key=lambda kv: kv[1], reverse=True)
            recommended_crops = [
                {"name": str(c), "confidence": round(float(p) * 100)}
                for c, p in pairs[:3]
                if p > 0
            ]
        except Exception:
            recommended_crops = [{"name": prediction, "confidence": 80}]

        return {
            "success":           True,
            "recommended_crop":  prediction,
            "recommended_crops": recommended_crops,
        }

    except Exception as exc:
        print(f"[CropRecommend] Prediction error: {exc}")
        return {
            "success":           False,
            "recommended_crop":  "Rice",
            "recommended_crops": [{"name": "Rice", "confidence": 80}],
            "error":             str(exc),
        }

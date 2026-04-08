"""
seed_service.py
───────────────
Weather-aware seed variety recommendation.

Public API
──────────
  get_seed_recommendation(crop, location=None, weather=None)
    → list[dict]  e.g. [{"name": "Swarna", "reason": "..."}, ...]

Backward compatibility
──────────────────────
  • First argument is still the crop name string — existing callers work.
  • Returns a list (previously strings, now dicts) — callers that need
    plain names can do [s["name"] for s in result].

Weather logic
─────────────
  temperature > 32 °C  → heat-tolerant varieties
  rainfall    > 150 mm → high-rainfall / water-resistant varieties
  rainfall    <  60 mm → drought-resistant varieties
  otherwise            → standard high-yield varieties

  Multiple conditions can apply; the function builds a ranked list with
  the most contextually appropriate varieties first.
"""

from __future__ import annotations


# ── Seed database ──────────────────────────────────────────────────────────────
# Structure: crop → category → [(variety_name, short_description)]
# Categories: standard | high_rainfall | drought | heat_tolerant
_SEED_DB: dict[str, dict[str, list[tuple[str, str]]]] = {
    "rice": {
        "standard": [
            ("IR64",      "High-yield semi-dwarf variety, widely adaptable"),
            ("MTU 1010",  "Popular in Andhra/Telangana, fine grain quality"),
            ("BPT 5204",  "Samba Masuri — premium aromatic, moderate yield"),
        ],
        "high_rainfall": [
            ("Swarna",    "Excellent submergence tolerance, ideal for flooded paddy"),
            ("IR 36",     "Flood-tolerant, short duration, widely grown"),
            ("Jaya",      "Robust under high moisture, pest-resistant"),
        ],
        "drought": [
            ("Sahbhagi",  "IRRI drought-tolerant variety for rainfed upland"),
            ("DRR Dhan 42", "Developed for water-scarce environments"),
            ("Vandana",   "Upland aerobic rice, minimal water requirement"),
        ],
        "heat_tolerant": [
            ("Naveen",    "Performs well under high-temperature stress"),
            ("Lalat",     "Short-duration, tolerates heat spikes at flowering"),
            ("Anjali",    "Stable yield under warm summer conditions"),
        ],
    },

    "wheat": {
        "standard": [
            ("HD 2967",   "Most widely grown wheat in India, excellent yield"),
            ("PBW 550",   "High protein, suited for Punjab/Haryana belt"),
            ("K 307",     "Long-standing UP cultivar, good baking quality"),
        ],
        "high_rainfall": [
            ("GW 496",    "Tolerates excess moisture during grain fill"),
            ("NW 1014",   "Suitable for high-humidity north-east plains"),
            ("HD 3043",   "Adapted to eastern wheat zone with higher rainfall"),
        ],
        "drought": [
            ("Raj 4120",  "Drought-tolerant Rajasthan selection"),
            ("WH 1105",   "Performs under limited irrigation in dry zones"),
            ("K 9107",    "Water-efficient, stable in moisture-deficit years"),
        ],
        "heat_tolerant": [
            ("HD 4530",   "Tolerates terminal heat stress at grain filling"),
            ("MACS 6222", "Early-maturing, escapes peak summer heat"),
            ("PBW 644",   "Heat-tolerant Punjabi variety for late sowing"),
        ],
    },

    "maize": {
        "standard": [
            ("DHM 117",   "High-yielding hybrid, dual-purpose grain and fodder"),
            ("Ganga 5",   "Composite variety, adaptable to diverse soils"),
            ("HM 4",      "Early maturity, suited for short growing season"),
        ],
        "high_rainfall": [
            ("Pro 311",   "Downy mildew-resistant, thrives in wet western zones"),
            ("NMH 803",   "High-moisture tolerance, good lodging resistance"),
            ("COH 3",     "Tamil Nadu hybrid with strong wet-season performance"),
        ],
        "drought": [
            ("DKC 9133",  "Drought-resilient, maintains yield under water stress"),
            ("HQPM 1",    "Quality protein maize tolerating dry spells"),
            ("Vivek QPM 9","High altitude, short duration, drought-enduring"),
        ],
        "heat_tolerant": [
            ("PEHM 2",    "Extended kernel fill under warm conditions"),
            ("DMRH 1301", "Heat and moisture stress tolerant hybrid"),
            ("Shaktiman 4","Robust grain development at elevated temperatures"),
        ],
    },

    "cotton": {
        "standard": [
            ("Bt Cotton RCH 134", "Bollworm-resistant hybrid, high ginning %"),
            ("MRC 7351",          "Long-staple, reliable in Vidarbha belt"),
            ("JK Durga",          "Stable performance across cotton zones"),
        ],
        "high_rainfall": [
            ("NHH 44",    "Tolerates waterlogging periods, reduces boll drop"),
            ("Suraj",     "Performs in high-humidity coastal Karnataka/AP"),
            ("LRA 5166",  "Rain-tolerant, widely cultivated in Marathwada"),
        ],
        "drought": [
            ("MCU 5",     "Short-duration, completes before dry season peaks"),
            ("F 2383",    "Low water-use efficiency, rainfed Deccan plateau"),
            ("G.Cot.10",  "Gujarat drought-tolerant desi cotton cultivar"),
        ],
        "heat_tolerant": [
            ("Vikram",    "Endures high day temperatures during boll formation"),
            ("LD 327",    "Summer cotton in Rajasthan, heat-stress tolerant"),
            ("Jayadhar",  "Long-season performance even in hot dry conditions"),
        ],
    },

    "sugarcane": {
        "standard": [
            ("CoJ 64",   "High sucrose, suited for Peninsular India"),
            ("Co 0238",  "Popular commercial variety, wide adaptability"),
            ("Co 86032", "Ratoon crop champion, good recoveries"),
        ],
        "high_rainfall": [
            ("CoS 767",  "Excellent germination in water-logged soils"),
            ("Co 0001",  "High rainfall zone in UP / Uttarakhand"),
            ("CoC 671",  "Tamil Nadu coastal belt, heavy rain tolerance"),
        ],
        "drought": [
            ("CoSe 92423","Drought escape via early maturity"),
            ("Co 0239",   "Water-deficit tolerant, Deccan plateau"),
            ("CoM 0265",  "Maharashtra drought-tolerant release"),
        ],
        "heat_tolerant": [
            ("CoJ 83",   "Withstands high temperature during grand growth"),
            ("CoJ 88",   "Short-duration, matures before peak summer"),
            ("CoA 92081","Andhra hot-weather performer"),
        ],
    },

    "soybean": {
        "standard": [
            ("JS 335",   "Most popular central India variety, consistent yield"),
            ("NRC 37",   "Short duration, high protein content"),
            ("MACS 58",  "Widely adaptable, good lodging resistance"),
        ],
        "high_rainfall": [
            ("JS 9560",  "Tolerates excess moisture during pod fill"),
            ("DSb 21",   "Performs in high-humidity Madhya Pradesh"),
            ("EC 538828","Waterlogging tolerance with good yield"),
        ],
        "drought": [
            ("SL 295",   "Drought-tolerant with maintained seed quality"),
            ("JS 97-52", "Low-moisture performance, reduced irrigation need"),
            ("RAUS 5",   "Rajasthan dry-zone selection"),
        ],
        "heat_tolerant": [
            ("PS 1347",  "Early maturing, escapes terminal heat"),
            ("UPSM 534", "Heat-stable oil content at high temperatures"),
            ("SL 688",   "Warm-climate performance in Vidarbha/MP"),
        ],
    },

    "groundnut": {
        "standard": [
            ("TAG 24",   "Short-duration, high oil content, South India"),
            ("TG 37A",   "Large bold seed, popular for direct consumption"),
            ("GG 20",    "Gujarat variety, excellent kernel recovery"),
        ],
        "high_rainfall": [
            ("ICGV 91114","Improved tolerance to late-season wet spells"),
            ("JL 24",     "Runners type, suits irrigated/rain-fed mix"),
            ("R 8808",    "High-rainfall Andhra coastal selection"),
        ],
        "drought": [
            ("ICGV 86031","ICRISAT drought-tolerant selection"),
            ("TMV 2",     "Traditional dry-zone variety, stable under stress"),
            ("VRI 2",     "Tamil Nadu release for moisture-deficit areas"),
        ],
        "heat_tolerant": [
            ("SunBred 11 R","Heat-tolerant pegging and pod fill"),
            ("ICGV 87846","Performs under high-temperature Rajasthan conditions"),
            ("GJG 31",    "Gujarat hot-climate runner type"),
        ],
    },

    "arecanut": {
        "standard": [
            ("Mangala",      "CPCRI release, high-yielding tall variety"),
            ("Sumangala",    "Dwarf variety, early bearer, suited for small farms"),
            ("Sreemangala",  "Short-statured, precocious, Kerala coastal belt"),
        ],
        "high_rainfall": [
            ("Mohitnagar",   "Assam selection, tolerates heavy monsoon"),
            ("Hirehalli Dwarf","Karnataka rainy-zone dwarf variety"),
            ("Sauparnika",   "Heavy rainfall tolerance, north Karnataka"),
        ],
        "drought": [
            ("Vittla Local", "Traditional variety with moderate drought tolerance"),
            ("Thirthahalli", "Karnataka interior, less water requirement"),
            ("Sagara Local", "Moderate irrigation requirement, Karnataka"),
        ],
        "heat_tolerant": [
            ("Mangala",      "Performs under warm lowland conditions"),
            ("Sumangala",    "Dwarf type, stable yield under heat"),
            ("Ankola Local", "Coastal Karnataka heat-tolerant landrace"),
        ],
    },

    "coconut": {
        "standard": [
            ("West Coast Tall (WCT)",     "Most common tall variety, high oil, 80+ nuts/palm/year"),
            ("Chowghat Orange Dwarf (COD)","Early bearing dwarf, tender nut for water"),
            ("Gangabondam",               "Andhra Pradesh popular variety"),
        ],
        "high_rainfall": [
            ("Lakshadweep Ordinary (LO)", "Island variety, thrives in humid maritime conditions"),
            ("Tiptur Tall",               "Karnataka coastal, heavy-monsoon adapted"),
            ("D×T Hybrid",                "Disease-resistant hybrid for high-rainfall zones"),
        ],
        "drought": [
            ("ECT (East Coast Tall)",     "Adaptable, moderate irrigation requirement"),
            ("Kappadam",                  "Kerala mid-land low-water variety"),
            ("Chandrakalpa",              "CPCRI hybrid with lower water need"),
        ],
        "heat_tolerant": [
            ("WCT × COD Hybrid",          "High yield under tropical heat conditions"),
            ("VHC-1",                     "Tamil Nadu tall × dwarf cross, heat stable"),
            ("Kalpasree",                 "Kerala hybrid, tolerates warm humid summers"),
        ],
    },

    "coffee": {
        "standard": [
            ("Cauvery (Catimor)",         "Compact plant, high yield, rust-resistant"),
            ("Selection 5 (S.5)",         "Robusta variety, commercial staple"),
            ("Selection 9 (S.9)",         "Arabica × Robusta hybrid, widely grown"),
        ],
        "high_rainfall": [
            ("S.274",                     "Robusta, ideal for high-rainfall Chikmagalur"),
            ("S.288",                     "Robusta, waterlogging tolerant lower elevations"),
            ("Chandragiri",               "Compact Arabica for wet Western Ghats"),
        ],
        "drought": [
            ("S.795",                     "Classic Arabica with good drought endurance"),
            ("Hemavathy",                 "CCRI Arabica selection, moderate-moisture zones"),
            ("Sln.9",                     "Hybrid with better water-use efficiency"),
        ],
        "heat_tolerant": [
            ("Robusta S.274",             "Higher temperature tolerance at lower elevations"),
            ("S.333",                     "Robusta for warmer sub-ghat zones"),
            ("Sln.13",                    "Heat-adaptive CCRI hybrid"),
        ],
    },

    "pepper": {
        "standard": [
            ("Panniyur-1",               "Most popular high-yielding variety, Kerala"),
            ("Karimunda",                "Traditional Kerala landrace, premium quality"),
            ("Sreekara",                 "IISR release, high yield, moderate vigour"),
        ],
        "high_rainfall": [
            ("Subhakara",                "IISR variety, wet Western Ghats performance"),
            ("Panchami",                 "Tolerates heavy rains, compact vine"),
            ("Pournami",                 "High-humidity zone adaptation"),
        ],
        "drought": [
            ("Cheriyakaniyakadan",       "Traditional dry-spell tolerant landrace"),
            ("IISR Thevam",              "Moderate drought-resilience IISR selection"),
            ("Shakthi",                  "Less water-intensive commercial variety"),
        ],
        "heat_tolerant": [
            ("Panniyur-5",              "Warm lowland adaptation, stable yield"),
            ("IISR Girimunda",          "Heat-stress tolerant IISR hybrid"),
            ("Aimpiriyan",              "Warm humid climate landrace"),
        ],
    },
}

# Fallback for unrecognised crops
_FALLBACK = [
    ("Certified Hybrid Seed",  "Consult your local KVK for variety-specific advice"),
    ("Open-Pollinated Variety","Budget-friendly, seed-saving compatible option"),
]

# ── Weather thresholds ────────────────────────────────────────────────────────
_TEMP_HEAT_THRESHOLD     = 32.0   # °C — above this → heat-tolerant
_RAIN_HIGH_THRESHOLD     = 150.0  # mm  — above this → high-rainfall
_RAIN_DROUGHT_THRESHOLD  = 60.0   # mm  — below this → drought

# How many varieties to return per recommendation
_TOP_N = 3


# ── internal helpers ──────────────────────────────────────────────────────────

def _resolve_weather(location: str | None, weather: dict | None) -> dict:
    """
    Return a weather dict with guaranteed temperature/humidity/rainfall.
    If a pre-fetched *weather* dict is supplied it is used directly (avoids
    a redundant network call when the crop pipeline already has weather data).
    Otherwise a live fetch is attempted using the existing _fetch_weather helper.
    """
    defaults = {"temperature": 25.0, "humidity": 60.0, "rainfall": 100.0}

    if weather and weather.get("temperature") is not None:
        return {**defaults, **weather}

    if not location:
        return defaults

    try:
        from routes.weather import _fetch_weather

        raw  = _fetch_weather(str(location).strip())
        temp = raw.get("temperature")
        hum  = raw.get("humidity")
        rain = raw.get("rainfall")

        if temp is not None:
            defaults["temperature"] = float(temp)
        if hum is not None:
            defaults["humidity"] = float(hum)
        if rain is not None:
            # rainfall from Open-Meteo is hourly mm → monthly approx
            defaults["rainfall"] = min(float(rain) * 720, 400.0)

    except Exception as exc:
        print(f"[SeedService] Weather fetch failed for '{location}': {exc}")

    return defaults


def _select_categories(temp: float, rainfall: float) -> list[tuple[str, str]]:
    """
    Return an ordered list of (category, reason_fragment) pairs based on
    the weather conditions.  Later items are lower priority.
    """
    picks: list[tuple[str, str]] = []

    if temp > _TEMP_HEAT_THRESHOLD and rainfall > _RAIN_HIGH_THRESHOLD:
        # Both hot and wet — heat-tolerant > high-rainfall > standard
        picks.append(("heat_tolerant",  f"heat-tolerant (temp {temp:.0f}°C > {_TEMP_HEAT_THRESHOLD:.0f}°C)"))
        picks.append(("high_rainfall",  f"water-resistant (rainfall {rainfall:.0f} mm > {_RAIN_HIGH_THRESHOLD:.0f} mm)"))
        picks.append(("standard",       "high-yield standard variety"))

    elif temp > _TEMP_HEAT_THRESHOLD and rainfall < _RAIN_DROUGHT_THRESHOLD:
        # Hot and dry — heat-tolerant + drought
        picks.append(("heat_tolerant",  f"heat-tolerant (temp {temp:.0f}°C > {_TEMP_HEAT_THRESHOLD:.0f}°C)"))
        picks.append(("drought",        f"drought-resistant (rainfall {rainfall:.0f} mm < {_RAIN_DROUGHT_THRESHOLD:.0f} mm)"))
        picks.append(("standard",       "high-yield standard variety"))

    elif temp > _TEMP_HEAT_THRESHOLD:
        picks.append(("heat_tolerant",  f"heat-tolerant (temp {temp:.0f}°C > {_TEMP_HEAT_THRESHOLD:.0f}°C)"))
        picks.append(("standard",       "high-yield standard variety"))
        picks.append(("drought",        "drought-resilient backup option"))

    elif rainfall > _RAIN_HIGH_THRESHOLD:
        picks.append(("high_rainfall",  f"water-resistant (rainfall {rainfall:.0f} mm > {_RAIN_HIGH_THRESHOLD:.0f} mm)"))
        picks.append(("standard",       "high-yield standard variety"))
        picks.append(("heat_tolerant",  "heat-resilient option for variability"))

    elif rainfall < _RAIN_DROUGHT_THRESHOLD:
        picks.append(("drought",        f"drought-resistant (rainfall {rainfall:.0f} mm < {_RAIN_DROUGHT_THRESHOLD:.0f} mm)"))
        picks.append(("standard",       "high-yield standard variety"))
        picks.append(("heat_tolerant",  "heat-resilient option for dry conditions"))

    else:
        picks.append(("standard",       "high-yield standard variety for moderate conditions"))
        picks.append(("high_rainfall",  "suitable if rainfall increases"))
        picks.append(("heat_tolerant",  "resilient option if temperatures rise"))

    return picks


# ── public API ────────────────────────────────────────────────────────────────

def get_seed_recommendation(
    crop:     str,
    location: str | None = None,
    weather:  dict | None = None,
) -> list[dict]:
    """
    Return weather-aware seed variety recommendations for *crop*.

    Args:
        crop:     Crop name string, e.g. "rice" or "Rice".
                  (First positional arg — unchanged from old API.)
        location: Optional location string for live weather fetch.
        weather:  Optional pre-fetched weather dict {temperature, humidity,
                  rainfall}.  When provided, skips the network call.

    Returns:
        list[dict] — each item: {"name": str, "reason": str}
        Empty list if the crop is completely unknown.

    Examples:
        get_seed_recommendation("rice")
        get_seed_recommendation("rice", location="Bangalore, Karnataka")
        get_seed_recommendation("rice", weather={"temperature": 34, "humidity": 70, "rainfall": 180})
    """
    if not crop:
        return []

    crop_key = str(crop).strip().lower()
    crop_db  = _SEED_DB.get(crop_key)

    # Resolve weather (use pre-fetched if available, else fetch, else defaults)
    wx = _resolve_weather(location, weather)
    temp     = float(wx.get("temperature") or 25.0)
    rainfall = float(wx.get("rainfall")    or 100.0)

    print(
        f"[SeedService] crop='{crop_key}' temp={temp:.1f}°C "
        f"rain={rainfall:.1f}mm location='{location}'"
    )

    if not crop_db:
        # Unknown crop — return fallback with generic reasons
        return [
            {"name": n, "reason": r} for n, r in _FALLBACK
        ]

    # Build selection priority based on weather
    category_picks = _select_categories(temp, rainfall)

    # When multiple conditions apply, take at most 1 variety from each
    # category so the response represents all relevant conditions, then
    # back-fill from the highest-priority category if slots remain.
    max_per_cat = 1 if len(category_picks) > 1 else _TOP_N

    seen:   set[str]    = set()
    result: list[dict]  = []

    # First pass — take up to max_per_cat from each category
    for category, reason_fragment in category_picks:
        taken = 0
        for name, description in crop_db.get(category, []):
            if name in seen:
                continue
            seen.add(name)
            result.append({
                "name":   name,
                "reason": f"{description} — recommended as {reason_fragment}",
            })
            taken += 1
            if taken >= max_per_cat or len(result) >= _TOP_N:
                break
        if len(result) >= _TOP_N:
            break

    # Back-fill pass — top-priority category first until _TOP_N reached
    for category, reason_fragment in category_picks:
        for name, description in crop_db.get(category, []):
            if len(result) >= _TOP_N:
                break
            if name not in seen:
                seen.add(name)
                result.append({
                    "name":   name,
                    "reason": f"{description} — recommended as {reason_fragment}",
                })
        if len(result) >= _TOP_N:
            break

    # Final safety pad with standard varieties
    for name, description in crop_db.get("standard", []):
        if len(result) >= _TOP_N:
            break
        if name not in seen:
            seen.add(name)
            result.append({
                "name":   name,
                "reason": f"{description} — high-yield standard variety",
            })

    return result

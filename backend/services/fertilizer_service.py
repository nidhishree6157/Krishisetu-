"""
fertilizer_service.py
─────────────────────
Rich, soil-aware fertilizer recommendation engine.

Supports all major Indian crops including plantation crops:
  Arecanut, Coffee, Pepper, Coconut — plus Rice, Wheat, Maize,
  Cotton, Sugarcane, Groundnut, Soybean, Tomato.

Public API
──────────
  get_fertilizer_plan(crop, nitrogen, phosphorus, potassium,
                      area=1.0, location=None)
    → dict  with keys: success, crop, fertilizer, unit,
                       additional, schedule, notes,
                       soil_status, adjustment_notes, explanation
"""

from __future__ import annotations

# ── Soil-nutrient classification thresholds (mg/kg) ──────────────────────────
# Source: ICAR / IARI standard interpretive ranges for Indian soils.
_N_LOW, _N_MED_HI  = 280.0, 560.0   # Nitrogen (available N)
_P_LOW, _P_MED_HI  =  11.0,  22.0   # Phosphorus (Olsen / Bray)
_K_LOW, _K_MED_HI  = 110.0, 280.0   # Potassium (exchangeable K)

# Dynamic adjustment factors
_INCREASE_LOW  = 0.20   # +20 % when soil nutrient is Low
_DECREASE_HIGH = 0.15   # -15 % when soil nutrient is High


def _classify(value: float, lo: float, hi: float) -> str:
    """Return 'Low', 'Medium', or 'High' for a soil nutrient value."""
    if value < lo:
        return "Low"
    if value > hi:
        return "High"
    return "Medium"


# ── Crop fertilizer database ───────────────────────────────────────────────────
# Structure per crop:
#   base_npk  – dict {N, P, K} in the crop's native unit (g or kg)
#   unit      – human-readable unit string
#   additional – list of supplemental inputs
#   schedule  – application timing string
#   notes     – important agronomic notes
#   n_sens / k_sens – True when dose should be adjusted by soil status
_CROP_DB: dict[str, dict] = {

    # ── PLANTATION CROPS ──────────────────────────────────────────────────────

    "arecanut": {
        "display":    "Arecanut",
        "base_npk":   {"N": 100, "P": 40, "K": 140},
        "unit":       "g/palm/year",
        "additional": [
            "Organic manure: 10–15 kg per palm/year (in basal pit)",
            "Magnesium sulphate: 200 g/palm — apply twice yearly",
            "Borax: 25 g/palm/year (foliar or soil — prevents 'kole roga')",
        ],
        "schedule": (
            "Apply in 2 equal splits — first dose in May–June "
            "(pre-monsoon) and second in September–October (post-monsoon). "
            "Avoid application during heavy rainfall."
        ),
        "notes": (
            "Ensure good drainage around the palm basin. "
            "Mulch with dry leaves (5–8 kg) to conserve moisture. "
            "Micronutrient deficiency (Mg, B) is common on laterite soils."
        ),
        "n_sens": True,
        "k_sens": True,
    },

    "coffee": {
        "display":    "Coffee",
        "base_npk":   {"N": 120, "P": 90, "K": 120},
        "unit":       "kg/ha/year",
        "additional": [
            "Compost: 2–5 kg/plant/year (incorporate in soil around drip circle)",
            "Lime (CaCO₃): 500 g/plant if soil pH < 5.5 (apply 4–6 weeks before fertilizer)",
            "Zinc sulphate + Boron foliar spray: twice yearly at 0.5 % concentration",
        ],
        "schedule": (
            "Apply in 3 split doses — first in April–May (pre-blossom), "
            "second in July (active growth after first flush), "
            "third in October (berry development). "
            "Split applications reduce leaching losses."
        ),
        "notes": (
            "Coffee prefers slightly acidic soil (pH 5.5–6.5). "
            "Test pH before lime application. "
            "Excess N promotes vegetative growth at the cost of berry quality — "
            "do not exceed 150 kg N/ha/year."
        ),
        "n_sens": True,
        "k_sens": False,
    },

    "pepper": {
        "display":    "Pepper",
        "base_npk":   {"N": 50, "P": 50, "K": 150},
        "unit":       "g/vine/year",
        "additional": [
            "Neem cake: 1 kg/vine/year (apply in June — suppresses soil pathogens)",
            "Organic compost / FYM: 5 kg/vine/year (mixed into soil)",
            "Well-decomposed FYM: 10 kg/vine in pit before planting / replenishment",
        ],
        "schedule": (
            "Apply in 2 splits — first dose in May–June "
            "(pre-monsoon, after first rains settle) and "
            "second in September (post-monsoon peak). "
            "Apply in a 30 cm radius ring around the base of the standard/support."
        ),
        "notes": (
            "Excellent drainage is critical — waterlogging causes Phytophthora foot rot. "
            "Mulching (10 cm layer) conserves moisture and suppresses weeds. "
            "Avoid applying fertilizer in dry soil; irrigate lightly before application."
        ),
        "n_sens": True,
        "k_sens": True,
    },

    "coconut": {
        "display":    "Coconut",
        "base_npk":   {"N": 500, "P": 320, "K": 1200},
        "unit":       "g/palm/year",
        "additional": [
            "Farmyard manure (FYM): 20–25 kg/palm/year (fill in basin pit)",
            "Magnesium sulphate: 500 g/palm/year (apply in basin)",
            "Borax: 50 g/palm/year if yellowing leaves observed",
            "Neem cake: 2 kg/palm — suppresses soil nematodes",
        ],
        "schedule": (
            "Apply in 2 equal splits — first in May–June (onset of monsoon) "
            "and second in October–November (post-monsoon). "
            "Apply in a circular basin 1.5–1.8 m from the trunk; "
            "cover with soil after each application."
        ),
        "notes": (
            "Coconut is a heavy potassium feeder — K deficiency causes 'button shedding'. "
            "Basin irrigation after fertilizer application improves uptake. "
            "Young palms (1–3 years) require only 50 % of the adult dose."
        ),
        "n_sens": False,
        "k_sens": True,
    },

    # ── FIELD / GRAIN CROPS ───────────────────────────────────────────────────

    "rice": {
        "display":    "Rice",
        "base_npk":   {"N": 120, "P": 60, "K": 60},
        "unit":       "kg/ha/season",
        "additional": [
            "Zinc sulphate: 25 kg/ha basal (in Zn-deficient soils — common in India)",
            "Neem-coated urea: reduces N volatilisation by 20–30 %",
        ],
        "schedule": (
            "Apply full P & K basal. "
            "Split N in 3 equal doses — basal at transplanting, "
            "at active tillering (21–25 DAT), and at panicle initiation (45–50 DAT)."
        ),
        "notes": (
            "Avoid flooding immediately after fertilizer application. "
            "In puddled soils, broadcast urea and incorporate. "
            "Silica supplement (silica slag) improves lodging resistance in coastal areas."
        ),
        "n_sens": True,
        "k_sens": True,
    },

    "wheat": {
        "display":    "Wheat",
        "base_npk":   {"N": 120, "P": 60, "K": 40},
        "unit":       "kg/ha/season",
        "additional": [
            "Sulphur: 20 kg/ha — SSP application covers this naturally",
            "Zinc sulphate: 25 kg/ha (if deficiency; once every 2–3 years)",
        ],
        "schedule": (
            "Apply full P, K, and half N as basal at sowing. "
            "Remaining N at crown-root initiation (21 DAS). "
            "If split further — apply 1/3 at sowing, 1/3 at CRI, 1/3 at flag-leaf."
        ),
        "notes": (
            "Late N application delays maturity and increases lodging. "
            "For late-sown wheat, reduce total N by 20 % and skip the last split. "
            "Avoid pre-sowing N as ammonia volatilisation is high in winter soils."
        ),
        "n_sens": True,
        "k_sens": False,
    },

    "maize": {
        "display":    "Maize",
        "base_npk":   {"N": 150, "P": 75, "K": 75},
        "unit":       "kg/ha/season",
        "additional": [
            "Zinc sulphate: 25 kg/ha basal (maize is highly Zn-sensitive)",
            "Boron: 1.5 kg/ha if tasselling abnormality observed",
        ],
        "schedule": (
            "Apply full P & K + 1/3 N at sowing. "
            "Side-dress 1/3 N at knee-high stage (V6, ~30 DAS). "
            "Top-dress remaining 1/3 N at tasselling (V12)."
        ),
        "notes": (
            "Maize responds strongly to split N application. "
            "Zinc deficiency ('white bud' / 'grey stripe') is very common — "
            "always apply ZnSO₄ where maize has not been grown before. "
            "Furrow application of DAP at sowing increases early vigour."
        ),
        "n_sens": True,
        "k_sens": True,
    },

    "cotton": {
        "display":    "Cotton",
        "base_npk":   {"N": 120, "P": 60, "K": 60},
        "unit":       "kg/ha/season",
        "additional": [
            "Sulphur: 30 kg/ha — use SSP over DAP for this crop",
            "Boron: 1.5 kg/ha foliar spray at bud formation (prevents boll shedding)",
        ],
        "schedule": (
            "Apply full P & K + half N at sowing. "
            "Split remaining N into 2 doses — at 30 DAS (squaring) "
            "and 60 DAS (flowering). "
            "Avoid N after 70 DAS to allow normal boll opening."
        ),
        "notes": (
            "Excess N promotes vegetative growth at the expense of boll development. "
            "Potassium improves fibre length and strength. "
            "In Bt cotton, watch for micronutrient deficiencies — Fe, Zn, Mg."
        ),
        "n_sens": True,
        "k_sens": False,
    },

    "sugarcane": {
        "display":    "Sugarcane",
        "base_npk":   {"N": 275, "P": 95, "K": 115},
        "unit":       "kg/ha/season",
        "additional": [
            "Trash mulching: incorporate sugarcane trash (5–7 t/ha) instead of burning",
            "Zinc sulphate: 25 kg/ha in Zn-deficient soils",
            "Biofertilizer (Gluconacetobacter): reduces N requirement by ~25 %",
        ],
        "schedule": (
            "Apply full P & K + 1/3 N at planting. "
            "Apply 1/3 N at 45 DAS (tillering). "
            "Apply remaining 1/3 N at grand growth stage (90–120 DAS). "
            "For ratoon crop, increase K by 20 %."
        ),
        "notes": (
            "Sugarcane removes large amounts of K from soil — replenish annually. "
            "Trash mulching returns ~50 kg N/ha equivalent to soil. "
            "Water-soluble fertilizers via drip irrigation ('fertigation') "
            "improve efficiency by 30–40 %."
        ),
        "n_sens": True,
        "k_sens": True,
    },

    "groundnut": {
        "display":    "Groundnut",
        "base_npk":   {"N": 25, "P": 50, "K": 50},
        "unit":       "kg/ha/season",
        "additional": [
            "Gypsum: 400–500 kg/ha at early pod formation (calcium + sulphur for kernel fill)",
            "Rhizobium + PSB seed treatment (can reduce N requirement by 50 %)",
            "Boron: 1 kg/ha foliar at pegging stage",
        ],
        "schedule": (
            "Apply full NPK as basal at sowing. "
            "Top-dress with 2 % DAP foliar spray at flowering (45 DAS). "
            "Apply gypsum at 30–35 DAS (pegging stage) — broadcast in rows."
        ),
        "notes": (
            "Groundnut is a legume — avoid excess N as it suppresses nodulation. "
            "Calcium from gypsum is critical for kernel development — "
            "acidic soils (pH < 6.0): also apply 2 t/ha lime before sowing. "
            "Sandy soils require split gypsum applications."
        ),
        "n_sens": False,
        "k_sens": True,
    },

    "soybean": {
        "display":    "Soybean",
        "base_npk":   {"N": 20, "P": 80, "K": 40},
        "unit":       "kg/ha/season",
        "additional": [
            "Rhizobium + PSB seed treatment (N fixation — critical)",
            "Sulphur: 20 kg/ha — prefer SSP over DAP",
            "Molybdenum: 100 g/ha seed treatment (boosts N fixation)",
        ],
        "schedule": (
            "Apply full NPK basal at sowing. "
            "Avoid additional N top-dressing — Rhizobium nodules supply N. "
            "Foliar micronutrient spray (Zn + B) at V4 stage if deficiency observed."
        ),
        "notes": (
            "If soil pH < 6.0, apply 2 t/ha lime at least 2 weeks before sowing. "
            "Soybean is a legume — its N fixing capacity (50–100 kg N/ha equivalent) "
            "reduces need for applied N. High P availability promotes pod filling."
        ),
        "n_sens": False,
        "k_sens": False,
    },

    "tomato": {
        "display":    "Tomato",
        "base_npk":   {"N": 120, "P": 80, "K": 120},
        "unit":       "kg/ha/season",
        "additional": [
            "Calcium nitrate: 5 kg/1000 L foliar spray to prevent blossom-end rot",
            "Boron: 1.5 kg/ha foliar spray at fruit set stage",
            "Magnesium sulphate: 0.5 % foliar spray at fruit development",
        ],
        "schedule": (
            "Apply 1/4 N + full P as basal. "
            "Apply remaining N in 3 equal splits — at 20, 40, and 60 DAT. "
            "Increase K by 25 % during fruit development. "
            "Fertigation through drip: apply weekly dilute solution."
        ),
        "notes": (
            "Tomato has high K demand at fruiting — potassium sulphate "
            "is preferred over MOP (chloride-free). "
            "Calcium deficiency causes blossom-end rot — maintain consistent irrigation "
            "for steady Ca uptake. Avoid ammonia-N sources in alkaline soils."
        ),
        "n_sens": True,
        "k_sens": True,
    },
}


def get_fertilizer_plan(
    crop: str,
    nitrogen: float = 0.0,
    phosphorus: float = 0.0,
    potassium: float = 0.0,
    area: float = 1.0,
    location: str | None = None,
) -> dict:
    """
    Return a rich fertilizer recommendation dict for *crop*.

    Soil nutrient values (mg/kg) are used to classify soil status and
    dynamically adjust N and K doses where agronomically appropriate.

    Args:
        crop       – crop name string (case-insensitive)
        nitrogen   – soil available N in mg/kg
        phosphorus – soil available P in mg/kg
        potassium  – soil available K in mg/kg
        area       – farm area in hectares (used only for per-ha crops)
        location   – optional location string for context in explanation

    Returns a dict with keys:
        success, crop, fertilizer {N, P, K}, unit,
        additional, schedule, notes,
        soil_status {nitrogen, phosphorus, potassium},
        adjustment_notes, explanation
    """
    key  = (crop or "").strip().lower()
    plan = _CROP_DB.get(key)

    if plan is None:
        # Generic fallback
        return {
            "success":          True,
            "crop":             crop or "Unknown",
            "fertilizer":       {"N": "120 kg/ha", "P": "60 kg/ha", "K": "60 kg/ha"},
            "unit":             "kg/ha/season",
            "additional":       ["Consult your nearest KVK for crop-specific micronutrient advice."],
            "schedule":         "Apply full P & K basal; split N in 2 equal doses.",
            "notes":            "Use balanced NPK 14-14-14 as a general starting point.",
            "soil_status":      _classify_all(nitrogen, phosphorus, potassium),
            "adjustment_notes": [],
            "explanation":      (
                f"No specific plan found for '{crop}'. "
                "A general NPK 14-14-14 schedule is recommended. "
                "Consult your local KVK for a tailored programme."
            ),
        }

    # ── Classify soil nutrients ───────────────────────────────────────────────
    n_status = _classify(nitrogen,   _N_LOW, _N_MED_HI)
    p_status = _classify(phosphorus, _P_LOW, _P_MED_HI)
    k_status = _classify(potassium,  _K_LOW, _K_MED_HI)

    # ── Copy base NPK and apply dynamic adjustments ───────────────────────────
    base   = plan["base_npk"].copy()
    adj_n  = base["N"]
    adj_p  = base["P"]
    adj_k  = base["K"]
    adj_notes: list[str] = []

    # Nitrogen adjustment
    if plan.get("n_sens"):
        if n_status == "Low":
            adj_n = round(base["N"] * (1 + _INCREASE_LOW))
            adj_notes.append(
                f"Soil nitrogen is Low ({nitrogen:.0f} mg/kg) — "
                f"N dose increased by 20 % to {adj_n} (from {base['N']})."
            )
        elif n_status == "High":
            adj_n = round(base["N"] * (1 - _DECREASE_HIGH))
            adj_notes.append(
                f"Soil nitrogen is High ({nitrogen:.0f} mg/kg) — "
                f"N dose reduced by 15 % to {adj_n} (from {base['N']})."
            )

    # Potassium adjustment
    if plan.get("k_sens"):
        if k_status == "Low":
            adj_k = round(base["K"] * (1 + _INCREASE_LOW))
            adj_notes.append(
                f"Soil potassium is Low ({potassium:.0f} mg/kg) — "
                f"K dose increased by 20 % to {adj_k} (from {base['K']})."
            )
        elif k_status == "High":
            adj_k = round(base["K"] * (1 - _DECREASE_HIGH))
            adj_notes.append(
                f"Soil potassium is High ({potassium:.0f} mg/kg) — "
                f"K dose reduced by 15 % to {adj_k} (from {base['K']})."
            )

    unit = plan["unit"]

    fertilizer = {
        "N": f"{adj_n} {_unit_suffix(unit)}",
        "P": f"{adj_p} {_unit_suffix(unit)}",
        "K": f"{adj_k} {_unit_suffix(unit)}",
    }

    # ── Build explanation ─────────────────────────────────────────────────────
    display   = plan["display"]
    loc_part  = f" in {location}" if location else ""
    base_desc = f"NPK {base['N']}:{base['P']}:{base['K']} {unit}"

    exp_lines = [
        f"{display}{loc_part} requires a base fertilizer programme of {base_desc}.",
    ]

    status_desc = _describe_soil(n_status, p_status, k_status,
                                 nitrogen, phosphorus, potassium)
    exp_lines.append(status_desc)

    if adj_notes:
        exp_lines.append(
            "Doses have been dynamically adjusted based on your soil analysis: "
            + " ".join(adj_notes)
        )
    else:
        exp_lines.append(
            "Your soil nutrient levels are within normal ranges — "
            "the standard recommended doses apply."
        )

    exp_lines.append(plan["notes"])

    return {
        "success":          True,
        "crop":             display,
        "fertilizer":       fertilizer,
        "unit":             unit,
        "additional":       plan["additional"],
        "schedule":         plan["schedule"],
        "notes":            plan["notes"],
        "soil_status":      {
            "nitrogen":   n_status,
            "phosphorus": p_status,
            "potassium":  k_status,
        },
        "adjustment_notes": adj_notes,
        "explanation":      "  ".join(exp_lines),
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _unit_suffix(unit: str) -> str:
    """Extract the unit measure (e.g. 'kg/ha/year') from a full unit string."""
    # Return the unit as-is — the numeric value already includes context
    return unit.split("/")[0].strip()   # e.g. "kg" or "g"


def _classify_all(n: float, p: float, k: float) -> dict:
    return {
        "nitrogen":   _classify(n, _N_LOW, _N_MED_HI),
        "phosphorus": _classify(p, _P_LOW, _P_MED_HI),
        "potassium":  _classify(k, _K_LOW, _K_MED_HI),
    }


def _describe_soil(n_st: str, p_st: str, k_st: str,
                   n: float, p: float, k: float) -> str:
    parts = []
    for label, status, val in (("Nitrogen", n_st, n),
                                ("Phosphorus", p_st, p),
                                ("Potassium", k_st, k)):
        parts.append(f"{label} {val:.0f} mg/kg ({status})")
    return "Your soil: " + ", ".join(parts) + "."

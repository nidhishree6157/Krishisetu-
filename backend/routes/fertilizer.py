from __future__ import annotations

import pymysql
from flask import Blueprint, jsonify, request, session

from db import DBConnectionError, get_db_connection
from services.farm_context_service import (
    SOIL_MESSAGE,
    fetch_farmer_row,
    fetch_soil_row,
    merge_farmer_profile_into_payload,
    merge_soil_into_payload,
    payload_has_soil_values,
    resolve_farmer_id,
)
from services.fertilizer_service import get_fertilizer_plan
from utils.helpers import login_required, role_required


fertilizer_bp = Blueprint("fertilizer", __name__)

_FALLBACK_FARMER_ID = 1   # used when session lookup fails (temporary)


def farmer_required(fn):
    return role_required("Farmer")(login_required(fn))


def get_fertilizer_recommendation(crop_or_data):
    """
    Return a fertilizer advice string.

    Accepts either:
      • a plain crop string  (backward-compatible – used by the route handler)
      • a dict {"pest": str, "crop": str}  (used by pest detection after AI inference)

    When a pest is supplied, pest-specific advice takes priority over generic crop advice.
    """
    if isinstance(crop_or_data, dict):
        crop = (crop_or_data.get("crop") or "").strip()
        pest = (crop_or_data.get("pest") or "").strip()
    else:
        crop = (crop_or_data or "").strip()
        pest = ""

    # Pest-specific fertilizer + treatment advice (takes priority)
    # Keys match LABELS in pest.py: Aphids, Armyworm, Whitefly, Leafhopper, Healthy
    _PEST_FERT: dict[str, str] = {
        "Aphids": (
            "Avoid excess nitrogen — it promotes soft growth that aphids favour. "
            "Apply potash-rich fertilizer (K2O 20 kg/acre). "
            "Spray neem oil (5 mL/L) or Imidacloprid 17.8 SL (0.5 mL/L) for chemical control."
        ),
        "Armyworm": (
            "Continue standard NPK — do not add extra nitrogen while infestation persists. "
            "Apply potassium supplementation (K2O) to strengthen plant cell walls. "
            "Use Chlorpyrifos 20 EC (2 mL/L) or Emamectin Benzoate 5 SG (0.4 g/L) for chemical control; "
            "Bt spray (2 g/L) for organic management."
        ),
        "Whitefly": (
            "Reduce nitrogen; use balanced NPK with extra potassium. "
            "Apply micronutrients (zinc + boron foliar spray). "
            "Spray Thiamethoxam 25 WG (0.3 g/L) or neem oil (10 mL/L)."
        ),
        "Leafhopper": (
            "Apply balanced NPK; avoid excess nitrogen which causes lush growth leafhoppers prefer. "
            "Foliar spray of zinc sulphate (0.5%) strengthens leaf tissue. "
            "Use Imidacloprid 17.8 SL (0.5 mL/L) or Buprofezin 25 SC (1 mL/L) for control."
        ),
        "Healthy": (
            "No pest-related changes needed. "
            "Maintain scheduled fertilizer application and field hygiene."
        ),
    }

    if pest and pest in _PEST_FERT:
        return _PEST_FERT[pest]

    # Crop-based fallback (expanded)
    _CROP_FERT: dict[str, str] = {
        "rice":      "Urea 50 kg/acre (basal) + Potash 20 kg/acre; top-dress with Urea at tillering",
        "wheat":     "DAP 20 kg/acre at sowing + Urea 25 kg/acre at tillering stage",
        "cotton":    "NPK 10-26-26 at sowing; Urea top-dress at squaring and flowering",
        "maize":     "NPK 20-20-0 at sowing + Zinc Sulphate 10 kg/acre",
        "tomato":    "NPK 19-19-19 fortnightly + Calcium-Boron foliar spray",
        "coconut":   "NPK 13-0-45 + Magnesium Sulphate 0.5 kg/palm twice yearly",
        "arecanut":  "NPK 100-40-140 g/palm/year split in two doses",
        "coffee":    "NPK 30-15-30 g/plant + organic compost annually",
        "pepper":    "NPK 50-50-150 g/vine/year + organic mulch",
        "sugarcane": "Urea 60 kg/acre + SSP 50 kg/acre + MOP 30 kg/acre",
        "groundnut": "SSP 100 kg/acre + Gypsum 200 kg/acre at pegging stage",
        "soybean":   "DAP 20 kg/acre (starter) + Rhizobium seed inoculant",
    }

    key = crop.lower() if crop else ""
    return _CROP_FERT.get(
        key,
        "General balanced fertilizer (NPK 14-14-14) — consult your nearest KVK for crop-specific advice.",
    )


@fertilizer_bp.post("/plan")
def fertilizer_plan():
    """
    POST /fertilizer/plan
    ─────────────────────
    Body (JSON):
      crop        – crop name string (required)
      nitrogen    – soil N in mg/kg   (optional — DB value used when absent)
      phosphorus  – soil P in mg/kg   (optional — DB value used when absent)
      potassium   – soil K in mg/kg   (optional — DB value used when absent)
      ph          – soil pH            (optional — DB value used when absent)
      area        – hectares           (default 1.0)
      location    – location string    (optional)

    Soil values are resolved in priority order:
      1. Manual value supplied in request body (> 0)
      2. Stored soil report in soil_data table for the current farmer
      3. 0.0 (standard base-rate doses apply)

    Response adds:
      "source"          – "soil_report" | "manual_input"
      "ph"              – resolved pH value (informational)
      "soil_source_note"– (present only when source == "soil_report")
    """
    data = request.get_json(silent=True) or {}

    soil_row = None
    farmer_id = _FALLBACK_FARMER_ID
    try:
        conn = get_db_connection()
        farmer_id = resolve_farmer_id(conn)
        farmer_row = fetch_farmer_row(conn, farmer_id)
        soil_row = fetch_soil_row(conn, farmer_id)
        merge_farmer_profile_into_payload(data, farmer_row)
        merge_soil_into_payload(data, soil_row)
    except DBConnectionError as exc:
        print(f"[Fertilizer] DB connection failed: {exc}")
    except Exception as exc:
        print(f"[Fertilizer] Profile/soil preload skipped: {exc}")

    crop = str(data.get("crop") or "").strip()
    if not crop:
        return jsonify({"success": False, "message": "crop is required"}), 400

    if not payload_has_soil_values(data):
        return jsonify({"success": False, "message": SOIL_MESSAGE}), 400

    # ── 2. Resolve each soil value: manual request → DB → 0 ──────────────────
    def _resolve(req_key: str, db_key: str) -> tuple[float, bool]:
        """
        Returns (value, from_db).
        'from_db' is True when the DB value was used instead of a manual one.
        A manual value of 0 is treated as absent (not a valid soil measurement).
        """
        manual = data.get(req_key)
        if manual is not None:
            try:
                v = float(manual)
                if v > 0:
                    return v, False   # valid manual input supplied
            except (TypeError, ValueError):
                pass

        if soil_row:
            db_val = soil_row.get(db_key)
            if db_val is not None:
                try:
                    return float(db_val), True   # use DB value
                except (TypeError, ValueError):
                    pass

        return 0.0, False   # no data available

    nitrogen,   n_db = _resolve("nitrogen",   "nitrogen")
    phosphorus, p_db = _resolve("phosphorus", "phosphorus")
    potassium,  k_db = _resolve("potassium",  "potassium")
    ph,         h_db = _resolve("ph",         "soil_ph")

    any_from_db = n_db or p_db or k_db or h_db
    source      = "soil_report" if any_from_db else "manual_input"

    # ── 3. Area — always from request (not stored in soil_data) ──────────────
    def _fv(key: str, default: float = 0.0) -> float:
        try:
            return float(data.get(key) or default)
        except (TypeError, ValueError):
            return default

    # ── 4. Generate plan (fertilizer_service is unchanged) ───────────────────
    plan = get_fertilizer_plan(
        crop       = crop,
        nitrogen   = nitrogen,
        phosphorus = phosphorus,
        potassium  = potassium,
        area       = _fv("area", 1.0),
        location   = str(data.get("location") or "").strip() or None,
    )

    # ── 5. Attach source metadata to response ─────────────────────────────────
    plan["source"]    = source
    plan["ph"]        = round(ph, 2) if ph else None
    plan["farmer_id"] = farmer_id     # informational; helps frontend debug

    if any_from_db:
        fields_used = [
            label for flag, label in [
                (n_db, "Nitrogen"),
                (p_db, "Phosphorus"),
                (k_db, "Potassium"),
                (h_db, "pH"),
            ] if flag
        ]
        plan["soil_source_note"] = (
            f"Soil values auto-loaded from your stored soil report "
            f"({', '.join(fields_used)}). "
            f"Provide manual values to override."
        )

    return jsonify(plan), 200


@fertilizer_bp.get("/recommend")
@farmer_required
def recommend_fertilizer():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM users WHERE user_id=%s LIMIT 1", (session["user_id"],))
            user_row = cur.fetchone() or {}
            username = user_row.get("username")

            crop = None
            if username:
                cur.execute("SELECT crop_type FROM farmers WHERE username=%s LIMIT 1", (username,))
                farmer_row = cur.fetchone() or {}
                crop = farmer_row.get("crop_type")

        fert = get_fertilizer_recommendation(crop)
        return jsonify({"success": True, "recommendations": [str(fert)]}), 200
    except DBConnectionError:
        return jsonify({"success": False, "message": "DB connection failed"}), 500
    except pymysql.MySQLError:
        return jsonify({"success": False, "message": "Database operation failed"}), 500
    except Exception:
        return jsonify({"success": False, "message": "Unexpected error"}), 500

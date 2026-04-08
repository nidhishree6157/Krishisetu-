from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from flask import Blueprint, jsonify, request, session
from sklearn.ensemble import RandomForestClassifier

from utils.helpers import json_error


ai_bp = Blueprint("ai", __name__)


_FEATURES = [
    "nitrogen",
    "phosphorus",
    "potassium",
    "temperature",
    "humidity",
    "ph",
    "rainfall",
]

# All crops the system can recommend (ML-trained + rule-based)
SUPPORTED_CROPS = [
    "Rice", "Wheat", "Maize", "Cotton", "Sugarcane",
    "Arecanut", "Coconut", "Coffee", "Pepper",
    "Soybean", "Groundnut", "Banana",
]


# ──────────────────────────────────────────────────────────────
# PLANTATION CROP RULE-BASED FALLBACK
# Applied when:
#   a) The ML model returns a low-confidence result, OR
#   b) Conditions strongly match a plantation crop profile
#      that is absent from the ML training set.
#
# Thresholds are derived from agro-climatic requirements of
# each crop for Indian conditions.
# Returns the best-matching plantation crop name, or None.
# ──────────────────────────────────────────────────────────────
def fallback_crop_logic(data: dict) -> str | None:
    """
    Rule-based plantation crop recommendation.

    Args:
        data: dict containing temperature, humidity, rainfall, ph
              (all optional — safe defaults used when missing).
    Returns:
        Crop name string if a strong match is found, else None.
    """
    def _f(key: str, default: float) -> float:
        try:
            return float(data.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    temp     = _f("temperature", 25.0)
    humidity = _f("humidity",    60.0)
    rainfall = _f("rainfall",   100.0)
    ph       = _f("ph",          6.5)

    # Score each plantation crop — higher = better match.
    # Only return a crop whose score clears a minimum threshold.
    candidates: list[tuple[str, float]] = []

    # ── RULE 1 — High rainfall + high humidity → Coconut or Arecanut ─────────
    # Matches user rule: rainfall > 200 AND humidity > 70.
    # Arecanut needs the extreme end (humidity ≥ 80); Coconut covers the rest.
    if rainfall > 200 and humidity > 70:
        if humidity >= 80:
            return "Arecanut"
        return "Coconut"

    # ── RULE 2 — Coffee ───────────────────────────────────────────────────────
    # Cool-climate elevation crop (Western Ghats, 800-1500 m).
    # User rule: temp 18–28°C AND moderate rainfall.
    # Upper rainfall capped at 220 mm here; above that Rule 1 handles Coconut.
    if 18 <= temp <= 28 and humidity >= 65 and 100 <= rainfall <= 220 and ph <= 7.0:
        return "Coffee"

    # ── RULE 3 — Arecanut (Betel Nut) ────────────────────────────────────────
    # Very high humidity (≥ 80%) is the strongest single indicator for arecanut
    # zones (coastal Karnataka / Assam / Northeast India).
    if 20 <= temp <= 32 and humidity >= 80 and rainfall > 150:
        return "Arecanut"

    # ── RULE 4 — Black Pepper ─────────────────────────────────────────────────
    # High humidity AND partial-shade conditions (proxied by humidity > 75%).
    # User rule: humidity high AND partial shade → Pepper.
    if 20 <= temp <= 32 and humidity > 75 and 120 <= rainfall <= 230 and ph <= 6.8:
        return "Pepper"

    # ── RULE 5 — Coconut ──────────────────────────────────────────────────────
    # Warm tropical climate with moderate humidity and broad rainfall tolerance.
    # Covers standard coastal / plains coconut-growing conditions.
    if 22 <= temp <= 35 and humidity > 68 and rainfall > 80:
        return "Coconut"

    return None


def _model_path() -> Path:
    # backend/models/crop_recommendation_model.pkl
    return Path(__file__).resolve().parents[1] / "models" / "crop_recommendation_model.pkl"


def _ensure_model_dir():
    p = _model_path().parent
    p.mkdir(parents=True, exist_ok=True)


def _train_fallback_model() -> RandomForestClassifier:
    """
    Fallback training data for demo purposes.
    If you add a real dataset later, replace this with loading CSV and training properly.
    """
    # Simple synthetic-ish samples around typical ranges.
    samples = [
        # rice (warm + high humidity + high rainfall)
        ([90, 40, 40, 27, 85, 6.5, 220], "rice"),
        ([80, 35, 35, 26, 88, 6.7, 200], "rice"),
        ([95, 45, 45, 28, 82, 6.4, 240], "rice"),
        # wheat (cooler + moderate rainfall)
        ([120, 50, 50, 18, 55, 6.8, 80], "wheat"),
        ([110, 45, 55, 20, 50, 7.0, 70], "wheat"),
        ([130, 55, 60, 17, 52, 6.9, 90], "wheat"),
        # maize (moderate temp + moderate humidity + moderate rainfall)
        ([100, 40, 60, 24, 65, 6.5, 120], "maize"),
        ([90, 35, 55, 25, 60, 6.6, 110], "maize"),
        ([105, 42, 65, 23, 68, 6.4, 130], "maize"),
        # cotton (warm + lower rainfall)
        ([60, 30, 40, 30, 50, 7.5, 60], "cotton"),
        ([65, 28, 38, 31, 48, 7.6, 55], "cotton"),
        ([55, 32, 42, 29, 52, 7.4, 65], "cotton"),
        # sugarcane (warm + high rainfall)
        ([140, 60, 80, 29, 75, 6.2, 180], "sugarcane"),
        ([135, 58, 78, 28, 78, 6.3, 190], "sugarcane"),
        ([145, 62, 82, 30, 72, 6.1, 170], "sugarcane"),
        # arecanut (warm, very humid, high rainfall, coastal)
        ([50, 30, 50, 24, 85, 6.5, 210], "arecanut"),
        ([45, 28, 48, 25, 88, 6.3, 230], "arecanut"),
        ([55, 32, 52, 23, 82, 6.7, 195], "arecanut"),
        # coconut (tropical coastal, moderate-high rainfall)
        ([65, 40, 100, 27, 78, 6.0, 160], "coconut"),
        ([60, 38, 95,  28, 75, 6.2, 170], "coconut"),
        ([70, 42, 105, 26, 80, 5.8, 150], "coconut"),
        # coffee (cooler + very humid + moderate rainfall + acidic)
        ([80, 40, 60, 22, 76, 6.0, 155], "coffee"),
        ([75, 38, 58, 20, 78, 5.8, 165], "coffee"),
        ([85, 42, 62, 24, 74, 6.2, 145], "coffee"),
        # pepper (tropical, high humidity, high rainfall)
        ([70, 35, 55, 25, 82, 6.0, 175], "pepper"),
        ([65, 33, 52, 27, 80, 5.9, 165], "pepper"),
        ([75, 37, 58, 23, 84, 6.1, 185], "pepper"),
    ]

    X = np.array([s[0] for s in samples], dtype=float)
    y = np.array([s[1] for s in samples], dtype=str)

    model = RandomForestClassifier(
        n_estimators=200,
        random_state=42,
    )
    model.fit(X, y)
    return model


def load_or_train_model():
    """
    Loads a pre-trained model if present, otherwise trains a simple model and saves it.
    """
    path = _model_path()
    try:
        if path.exists():
            return joblib.load(path)
    except Exception:
        # If load fails, fall back to retraining.
        pass

    _ensure_model_dir()
    model = _train_fallback_model()
    try:
        joblib.dump(model, path)
    except Exception:
        # Saving is optional; ignore failure.
        pass
    return model


def _parse_numeric_fields(payload: dict):
    missing = [k for k in _FEATURES if k not in payload]
    if missing:
        return None, {"message": "Missing required fields", "missing": missing}, 400

    values = []
    invalid = []
    for k in _FEATURES:
        v = payload.get(k)
        try:
            values.append(float(v))
        except Exception:
            invalid.append(k)

    if invalid:
        return None, {"message": "All fields must be numeric", "invalid": invalid}, 400

    return np.array(values, dtype=float).reshape(1, -1), None, None


def _is_crop_query(message: str) -> bool:
    text = str(message or "").lower()
    crop_terms = [
        "crop",
        "predict",
        "prediction",
        "recommend",
        "recommendation",
        "soil",
        "nitrogen",
        "phosphorus",
        "potassium",
        "rainfall",
        "ph",
        "humidity",
    ]
    return any(term in text for term in crop_terms)


def _rule_based_reply(message: str) -> tuple[str, str]:
    text = str(message or "").strip().lower()
    if not text:
        return "Please ask a question so I can help you.", "low"
    if any(k in text for k in ["hello", "hi", "hey"]):
        return "Hello! I can help with crop, soil, weather, pest, and fertilizer guidance.", "high"
    if any(k in text for k in ["weather", "rain", "temperature"]):
        return "For weather-based planning, check forecast before irrigation and spraying.", "high"
    if any(k in text for k in ["pest", "insect", "bug"]):
        return "Inspect leaves early morning and use integrated pest management to reduce loss.", "high"
    if any(k in text for k in ["fertilizer", "nutrient", "urea", "dap"]):
        return "Apply fertilizer based on soil test values and split nitrogen doses for better uptake.", "high"
    return "I can assist with agriculture topics. Ask about crop prediction, pests, weather, or soil care.", "low"


def _escalate_to_expert_queries(query_text: str) -> bool:
    """
    Insert a pending expert query (same pattern as expert submit_query: farmer_id from session or 1).
    Does not modify expert routes.
    """
    from db import get_db_connection

    try:
        conn = get_db_connection()
        farmer_id = None
        username = session.get("username")
        if username:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1",
                    (username,),
                )
                row = cur.fetchone()
                if row:
                    farmer_id = row.get("farmer_id")
        if not farmer_id:
            farmer_id = 1

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO expert_queries (farmer_id, expert_id, query_text, query_date, status)
                VALUES (%s, NULL, %s, NOW(), 'Pending')
                """,
                (farmer_id, query_text),
            )
        return True
    except Exception:
        return False


@ai_bp.post("/chatbot")
@ai_bp.post("/api/chatbot")
def chatbot():
    try:
        data = request.get_json(silent=True) or {}
        message = str(data.get("message") or "").strip()
        if not message:
            return jsonify({"reply": "message is required", "confidence": "low"}), 400

        if _is_crop_query(message):
            model = load_or_train_model()
            # Basic chatbot prediction uses safe defaults when no structured features are provided.
            X = np.array([[90.0, 40.0, 40.0, 25.0, 60.0, 6.5, 100.0]], dtype=float)
            pred = model.predict(X)[0]
            return jsonify(
                {
                    "reply": f"Based on current default conditions, the suggested crop is {pred}.",
                    "confidence": "high",
                    "escalated": False,
                }
            ), 200

        reply, confidence = _rule_based_reply(message)
        if confidence == "low":
            escalated = _escalate_to_expert_queries(message)
            return jsonify({"reply": reply, "escalated": escalated}), 200

        return jsonify({"reply": reply, "confidence": confidence, "escalated": False}), 200
    except Exception:
        return jsonify(
            {
                "reply": "I could not process your request right now. Please try again.",
                "confidence": "low",
            }
        ), 500


@ai_bp.post("/crop-recommendation")
def crop_recommendation():
    try:
        data = request.json or {}
        
        # Get username from session
        username = session.get("username")
        if not username:
            return json_error("Authentication required", 401)

        from db import get_db_connection

        conn = get_db_connection()
        with conn.cursor() as cur:
            # Try to fetch soil data from farmer profile
            cur.execute("SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1", (username,))
            farmer = cur.fetchone()
            
            soil_row = None
            if farmer:
                farmer_id = farmer.get("farmer_id")
                cur.execute("SELECT * FROM soil_data WHERE farmer_id=%s LIMIT 1", (farmer_id,))
                soil_row = cur.fetchone()

        # Use provided form inputs OR soil_row data with fallback defaults
        nitrogen = data.get("nitrogen") or (soil_row.get("nitrogen") if soil_row else 90)
        phosphorus = data.get("phosphorus") or (soil_row.get("phosphorus") if soil_row else 40)
        potassium = data.get("potassium") or (soil_row.get("potassium") if soil_row else 40)
        soil_ph = data.get("ph") or (soil_row.get("soil_ph") if soil_row else 6.5)
        temperature = data.get("temperature") or 25.0
        humidity = data.get("humidity") or 60.0
        rainfall = data.get("rainfall") or 100.0

        # Prepare model input
        X = np.array(
            [[
                float(nitrogen),
                float(phosphorus),
                float(potassium),
                float(temperature),
                float(humidity),
                float(soil_ph),
                float(rainfall)
            ]],
            dtype=float,
        )

        # Predict
        model = load_or_train_model()
        pred = str(model.predict(X)[0])

        # If the model is unsure (low proba) or returns a non-plantation
        # result but conditions clearly favour a plantation crop, apply
        # the rule-based fallback to inject the better answer.
        try:
            proba      = model.predict_proba(X)[0]
            top_prob   = float(max(proba))
            LOW_CONF   = 0.40          # threshold below which we trust rules more
            if top_prob < LOW_CONF or pred.lower() not in [
                c.lower() for c in SUPPORTED_CROPS[:5]  # original 5 ML crops
            ]:
                rule_crop = fallback_crop_logic({
                    "temperature": float(temperature),
                    "humidity":    float(humidity),
                    "rainfall":    float(rainfall),
                    "ph":          float(soil_ph),
                })
                if rule_crop:
                    print(
                        f"[AI] ML pred='{pred}' conf={top_prob:.0%} -> "
                        f"rule override -> '{rule_crop}'"
                    )
                    pred = rule_crop
        except Exception as fb_exc:
            print(f"[AI] Fallback check skipped: {fb_exc}")

        return jsonify({"success": True, "data": {"crop": pred}}), 200

    except Exception as e:
        return json_error("Crop recommendation failed", 500, error=str(e))


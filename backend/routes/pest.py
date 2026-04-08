from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from flask import Blueprint, jsonify, request, session
from PIL import Image

from routes.fertilizer import get_fertilizer_recommendation
from utils.helpers import json_error, login_required


pest_bp = Blueprint("pest", __name__)

# ── Image-based AI detection (added alongside existing text-based /recommend) ─

_MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
_MODEL_PATH = _MODELS_DIR / "pest_model.h5"

_model      = None
_model_lock = threading.Lock()
_model_ok   = None     # None = not tried, True = loaded, False = missing/broken

# Labels — must match the Dense output order in pest_model.h5
# Index: 0=Aphids  1=Armyworm  2=Whitefly  3=Leafhopper  4=Healthy
LABELS = ["Aphids", "Armyworm", "Whitefly", "Leafhopper", "Healthy"]

# ── Pest knowledge base ───────────────────────────────────────────────────────
_PEST_KB: dict[str, dict] = {
    "Aphids": {
        "severity":      "Medium",
        "explanation":   "Tiny soft-bodied insects that cluster on new growth and suck plant sap, causing leaf curl and yellowing.",
        "treatment":     "Spray neem oil (5 mL/L) or insecticidal soap. Imidacloprid 17.8 SL at 0.5 mL/L for severe infestation.",
        "prevention":    "Introduce ladybug predators. Avoid excess nitrogen which promotes soft growth. Use yellow sticky traps.",
        "organic_option":"Diluted neem oil or garlic-chilli spray every 7 days. Reflective mulches deter aphids.",
        "urgency":       "Treat within 1 week — colonies double rapidly",
    },
    "Armyworm": {
        "severity":      "High",
        "explanation":   "Caterpillar pest (Spodoptera species) that moves in large groups and strips foliage, stems, and grain.",
        "treatment":     "Apply Chlorpyrifos 20 EC (2 mL/L) or Emamectin Benzoate 5 SG (0.4 g/L). Install pheromone traps.",
        "prevention":    "Monitor with pheromone traps. Practice crop rotation. Early-season planting reduces risk.",
        "organic_option":"Bt (Bacillus thuringiensis) spray (2 g/L) is highly effective. Neem-based insecticides deter feeding.",
        "urgency":       "Act immediately — armyworms cause rapid and devastating defoliation",
    },
    "Whitefly": {
        "severity":      "High",
        "explanation":   "Small white flying insects that suck sap and transmit viruses like Leaf Curl Virus and Geminiviruses.",
        "treatment":     "Apply Thiamethoxam 25 WG (0.3 g/L) or Acetamiprid 20 SP (0.2 g/L). Remove heavily infested leaves.",
        "prevention":    "Use yellow sticky traps. Install insect-proof netting. Remove weeds that act as alternate hosts.",
        "organic_option":"Spray neem oil (10 mL/L) + mild soap. Reflective silver mulch disrupts whitefly orientation.",
        "urgency":       "Act within 48 hours — whiteflies spread viruses rapidly",
    },
    "Leafhopper": {
        "severity":      "Medium",
        "explanation":   "Small wedge-shaped insects that pierce leaves and suck sap, causing hopper burn and transmitting diseases.",
        "treatment":     "Apply Imidacloprid 17.8 SL (0.5 mL/L) or Buprofezin 25 SC (1 mL/L). Use light traps at night.",
        "prevention":    "Avoid dense planting. Remove crop residues after harvest. Use resistant varieties where available.",
        "organic_option":"Neem oil spray (5 mL/L) every 10 days. Sticky yellow traps for monitoring and mass trapping.",
        "urgency":       "Treat within 5-7 days — populations escalate quickly in warm conditions",
    },
    "Healthy": {
        "severity":      "None",
        "explanation":   "No pest detected. The plant appears pest-free.",
        "treatment":     "No treatment required.",
        "prevention":    "Continue field monitoring every 7-10 days. Maintain balanced nutrition and good plant hygiene.",
        "organic_option":"No action required.",
        "urgency":       "No immediate action required",
    },
}


# ── Thread-safe lazy model loader ─────────────────────────────────────────────
def _get_model():
    global _model, _model_ok

    if _model_ok is True:
        return _model

    with _model_lock:
        if _model_ok is True:
            return _model

        if not _MODEL_PATH.exists():
            print(f"[Pest] Model NOT found at {_MODEL_PATH}")
            print("[Pest] Run:  python models/create_pest_model.py")
            _model_ok = False
            return None

        try:
            from tensorflow.keras.models import load_model as _keras_load
            _model    = _keras_load(str(_MODEL_PATH))
            _model_ok = True
            print(f"[Pest] Model loaded  input_shape={_model.input_shape}")
        except Exception as exc:
            print(f"[Pest] Model load failed: {exc}")
            _model_ok = False

    return _model


# ── Image preprocessing ───────────────────────────────────────────────────────
def _preprocess(file) -> np.ndarray:
    """Resize to 224×224 and normalise to [0, 1]."""
    img = Image.open(file).convert("RGB").resize((224, 224))
    arr = np.array(img, dtype="float32") / 255.0
    return np.expand_dims(arr, axis=0)


def _norm_text(v: str) -> str:
    return str(v or "").strip().lower()


@pest_bp.post("/recommend")
@login_required
def recommend_pest():
    data = request.get_json(silent=True) or {}

    crop = data.get("crop")
    symptom = data.get("symptom")

    missing = [k for k in ("crop", "symptom") if not data.get(k)]
    if missing:
        return json_error("Missing required fields", 400, missing=missing)

    crop_n = _norm_text(crop)
    symptom_n = _norm_text(symptom)

    # Rule-based recommendations (no ML).
    # These rules are matched by normalized exact text.
    rules = [
        # Rice
        ("rice", "yellow leaves", "Leaf Folder", "Use neem oil spray"),
        ("rice", "brown spots", "Brown Spot Disease", "Use fungicide spray"),
        ("rice", "yellowing", "Leaf Blight", "Improve drainage and apply appropriate fungicide"),
        ("rice", "white powder", "Powdery Mildew", "Use sulfur-based fungicide"),
        # Wheat
        ("wheat", "white powder", "Powdery Mildew", "Use sulfur fungicide"),
        ("wheat", "rust", "Wheat Rust", "Apply rust-resistant treatment and fungicide"),
        # Maize
        ("maize", "wilting", "Maize Stem Borer", "Install pheromone traps and apply approved insecticide"),
        ("maize", "yellow streaks", "Maize Leaf Blight", "Use leaf blight control fungicide"),
        # Cotton
        ("cotton", "leaf curl", "Cotton Leaf Curl Virus", "Remove infected plants and control whiteflies"),
        ("cotton", "chewing insects", "Chewing Insects", "Use neem-based insect repellent or approved insecticide"),
    ]

    for rule_crop, rule_symptom, pest, solution in rules:
        if crop_n == rule_crop and symptom_n == rule_symptom:
            return jsonify({"success": True, "pest": pest, "solution": solution}), 200

    # Default case
    return jsonify({"success": True, "message": "No known pest found"}), 200


# ── Image-based AI pest detection ─────────────────────────────────────────────

@pest_bp.route("/predict", methods=["POST"])
@login_required
def predict_pest():
    """
    POST /pest/predict
    Upload a plant/leaf image → AI detects pest → returns label + full advice.
    Falls back to demo mode when pest_model.h5 is absent.
    """
    print("[Pest] /predict called  user:", session.get("username"))

    if "image" not in request.files:
        return json_error("Image is required", 400)

    file = request.files["image"]
    if not file or not getattr(file, "filename", ""):
        return json_error("Image is required", 400)

    crop_type = request.form.get("crop_type") or request.form.get("cropType") or ""

    # Preprocess
    try:
        arr = _preprocess(file)
        file.seek(0)
    except Exception:
        return jsonify({"success": False, "message": "Invalid or unreadable image"}), 400

    # Load model — return error if not available (no demo fallback)
    model = _get_model()
    if model is None:
        return jsonify({
            "success": False,
            "message": (
                "Pest detection model is not available. "
                "Run: python models/create_pest_model.py"
            ),
        }), 503

    # Run inference
    try:
        preds      = model.predict(arr, verbose=0)
        idx        = int(np.argmax(preds[0]))
        confidence = float(np.max(preds[0]))
        label      = LABELS[idx] if idx < len(LABELS) else "Unknown"
    except Exception as exc:
        print(f"[Pest] Prediction error: {exc}")
        return jsonify({"success": False, "message": "Prediction failed. Please try again."}), 500

    # Enrich with knowledge-base advice
    info = _PEST_KB.get(label, {
        "severity":      "Unknown",
        "explanation":   f"Detected: {label}. Consult an agronomist for details.",
        "treatment":     "Consult your nearest KVK or agriculture officer.",
        "prevention":    "Maintain good field hygiene and monitor regularly.",
        "organic_option":"Neem oil spray (5 mL/L) as a general precaution.",
        "urgency":       "Seek expert advice",
    })

    # Fertilizer/pesticide recommendation based on detected pest + crop
    fertilizer = get_fertilizer_recommendation({"pest": label, "crop": crop_type})
    if not fertilizer:
        fertilizer = "No specific treatment found. Use general pest control methods."

    return jsonify({
        "success":          True,
        "label":            label,
        "pest":             label,          # backward-compat alias
        "confidence":       round(confidence, 4),
        "confidence_pct":   f"{confidence * 100:.1f}%",
        "severity":         info["severity"],
        "is_healthy":       label == "Healthy",
        "explanation":      info["explanation"],
        "treatment":        info["treatment"],
        "prevention":       info["prevention"],
        "organic_option":   info["organic_option"],
        "urgency":          info["urgency"],
        "fertilizer":       fertilizer,
        "crop_type":        crop_type,
    }), 200


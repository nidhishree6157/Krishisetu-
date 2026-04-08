"""
disease.py
──────────
Plant disease detection endpoint.

POST /disease/predict
  Upload a plant/leaf image → model runs inference → enriched result.

POST /disease/detect
  Alias for /disease/predict (backward compatibility with old clients).

The route loads the Keras model lazily on first request using a thread-safe
double-checked lock, so it does not block application startup.

If the model file is absent the endpoint returns a clearly-labelled
"demo mode" result using rule-based logic so the UI always works.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
from flask import Blueprint, jsonify, request, session
from PIL import Image

from db import get_db_connection
from services.disease_service import enrich_prediction
from utils.helpers import json_error, login_required


disease_bp = Blueprint("disease", __name__)

# ── Model / metadata paths ────────────────────────────────────────────────────
_MODELS_DIR  = Path(__file__).resolve().parents[1] / "models"
_MODEL_PATH  = _MODELS_DIR / "disease_model.h5"
_META_PATH   = _MODELS_DIR / "disease_model_meta.json"


# ── Load class labels from metadata JSON (falls back to hardcoded list) ───────
def _load_labels() -> list[str]:
    """
    Read the disease class labels produced at model-build time.

    The meta file uses the key  "labels"  (not "classes").  If the file is
    absent or the key is missing the hardcoded fallback keeps the system
    running so startup never fails.
    """
    try:
        with open(_META_PATH, encoding="utf-8") as fh:
            meta = json.load(fh)
        labels = meta.get("labels") or meta.get("classes")
        if labels and isinstance(labels, list):
            print(f"[Disease] Labels loaded from meta: {labels}")
            return labels
    except Exception as exc:
        print(f"[Disease] Could not load labels from {_META_PATH}: {exc} — using defaults")
    return ["Leaf Blight", "Powdery Mildew", "Rust", "Healthy"]


LABELS: list[str] = _load_labels()

# ── Crop → expected disease labels (for mismatch advisory) ───────────────────
# Used ONLY to add a non-blocking "note" field when the detected disease is
# not typical for the selected crop.  The label itself is never overridden.
CROP_DISEASE_MAP: dict[str, list[str]] = {
    "rice":      ["Leaf Blight", "Brown Spot", "Rust", "Healthy"],
    "wheat":     ["Leaf Blight", "Rust", "Powdery Mildew", "Healthy"],
    "corn":      ["Leaf Blight", "Rust", "Healthy"],
    "tomato":    ["Leaf Blight", "Powdery Mildew", "Healthy"],
    "potato":    ["Leaf Blight", "Rust", "Healthy"],
    "cotton":    ["Leaf Blight", "Healthy"],
    "sugarcane": ["Rust", "Healthy"],
    # Plantation crops
    "coconut":   ["Bud Rot", "Leaf Rot", "Healthy"],
    "arecanut":  ["Yellow Leaf Disease", "Fruit Rot", "Healthy"],
    "coffee":    ["Coffee Leaf Rust", "Berry Disease", "Rust", "Healthy"],
    "pepper":    ["Quick Wilt", "Anthracnose", "Healthy"],
}

# ── Thread-safe lazy model loader ─────────────────────────────────────────────
_model      = None
_model_lock = threading.Lock()
_model_ok   = None        # True = loaded, False = missing/broken, None = not tried


def _get_model():
    global _model, _model_ok

    print("MODEL PATH:", _MODEL_PATH)

    if _model_ok is True:
        return _model

    with _model_lock:
        if _model_ok is True:
            return _model

        if not _MODEL_PATH.exists():
            print(
                f"[Disease] Model not found at {_MODEL_PATH}\n"
                "  Run:  python models/create_disease_model.py   to create it.\n"
                "  Falling back to demo mode."
            )
            _model_ok = False
            return None

        try:
            from tensorflow.keras.models import load_model as _keras_load
            _model    = _keras_load(str(_MODEL_PATH))
            _model_ok = True
            shape = getattr(_model, "input_shape", "unknown")
            print(f"[Disease] Model loaded  input_shape={shape}")
            print(f"MODEL INPUT SHAPE: {shape}")
        except Exception as exc:
            print(f"[Disease] Model load failed: {exc} — using demo mode")
            _model_ok = False

    return _model


# ── Image preprocessing ───────────────────────────────────────────────────────

def _preprocess(file) -> np.ndarray:
    """
    Open image file, resize to the model's expected input, normalise to [0,1].
    Reads input dimensions directly from the loaded model so the code stays
    valid if the model is swapped for one with a different resolution.
    """
    model = _get_model()

    # Determine expected spatial dimensions
    w, h = 224, 224
    if model is not None:
        try:
            shape = model.input_shape  # e.g. (None, 224, 224, 3)
            if shape and len(shape) >= 4 and isinstance(shape[1], int):
                h, w = shape[1], shape[2]
        except Exception:
            pass

    img = Image.open(file).convert("RGB").resize((w, h))
    arr = np.array(img, dtype="float32") / 255.0
    return np.expand_dims(arr, axis=0)           # (1, h, w, 3)


# ── Demo-mode fallback (used when model file is absent) ──────────────────────
def _demo_predict(image_file) -> tuple[str, float]:
    """
    Deterministic demo prediction — no TensorFlow required.
    Uses the image file's byte-level checksum to pick a consistent label
    so the same image always gives the same result.
    """
    data = image_file.read()
    image_file.seek(0)               # reset so PIL can still read it
    checksum = sum(data) % len(LABELS)
    label = LABELS[checksum]
    confidence = 0.72 + (sum(data[:32]) % 20) / 100   # 0.72 – 0.91
    return label, confidence


# ── DB helper ─────────────────────────────────────────────────────────────────
_FALLBACK_FARMER_ID = 1   # used when no session is present (temporary)

def _save_alert(disease: str) -> None:
    """
    Persist a disease detection event to disease_alerts (best-effort).
    Always inserts: uses the session farmer when available, falls back to
    farmer_id=1 so the notification feed is always populated.
    """
    try:
        conn = get_db_connection()
        farmer_id = _FALLBACK_FARMER_ID

        username = session.get("username")
        if username:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1",
                    (username,),
                )
                row = cur.fetchone()
                if row and row.get("farmer_id"):
                    farmer_id = row["farmer_id"]

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO disease_alerts (farmer_id, disease_name, alert_date) "
                "VALUES (%s, %s, NOW())",
                (farmer_id, disease),
            )
        conn.commit()
        print(f"[Disease] Alert saved — farmer_id={farmer_id} disease='{disease}'")
    except Exception as exc:
        print(f"[Disease] Alert save failed: {exc}")


# ── Shared detection logic ────────────────────────────────────────────────────
def _run_detection():
    """
    Common handler used by both /predict and /detect endpoints.
    Returns a Flask response object.
    """
    if "image" not in request.files:
        return json_error("Image is required", 400)

    file = request.files["image"]
    if not file or not getattr(file, "filename", ""):
        return json_error("Image is required", 400)

    crop_type = request.form.get("crop_type") or request.form.get("cropType")

    # ── Preprocess ──────────────────────────────────────────────────────────
    try:
        arr = _preprocess(file)
        file.seek(0)         # reset for demo fallback
    except Exception:
        return jsonify({"success": False, "message": "Invalid or unreadable image"}), 400

    # ── Predict ─────────────────────────────────────────────────────────────
    model = _get_model()
    demo_mode = model is None

    if demo_mode:
        # Model missing — use byte-hash demo
        label, confidence = _demo_predict(file)
        source = "demo"
    else:
        try:
            preds      = model.predict(arr, verbose=0)
            idx        = int(np.argmax(preds[0]))
            confidence = float(np.max(preds[0]))
            label      = LABELS[idx] if idx < len(LABELS) else "Unknown"
            source     = "model"
        except Exception as exc:
            print(f"[Disease] Prediction error: {exc}")
            return jsonify({
                "success": False,
                "message": "Prediction failed. Please try again.",
            }), 500

    # ── Enrich with treatment / prevention info ──────────────────────────────
    result = enrich_prediction(label, confidence, crop_type=crop_type)
    result["source"] = source          # "model" or "demo"
    if demo_mode:
        result["demo_note"] = (
            "Model file not found — showing demo results. "
            "Run  python models/create_disease_model.py  to enable real inference."
        )

    # ── Crop-disease mismatch advisory (non-blocking) ────────────────────────
    # If the detected disease is not in the expected list for the selected
    # crop, add a "note" field to prompt the user to verify with an expert.
    # The label is intentionally NOT overridden — the model result stands.
    if crop_type:
        allowed = CROP_DISEASE_MAP.get(crop_type.lower(), [])
        if allowed and label not in allowed:
            result["note"] = (
                f"'{label}' is not commonly associated with {crop_type.title()}. "
                "Consider verifying with a local agronomist or KVK."
            )

    # ── Persist alert (best-effort — never blocks the response) ─────────────
    _save_alert(label)

    return jsonify(result), 200


# ── Endpoints ─────────────────────────────────────────────────────────────────

@disease_bp.post("/predict")
def predict_disease():
    """Primary endpoint used by disease.html."""
    return _run_detection()


@disease_bp.post("/detect")
@login_required
def detect_disease():
    """Alias — kept for backward compatibility with any old client code."""
    return _run_detection()

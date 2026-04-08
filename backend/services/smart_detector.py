"""
smart_detector.py
─────────────────
Unified AI inference service that runs BOTH disease and pest detection
on a single uploaded image in one call.

Design
──────
  • Both models are loaded lazily and cached per-process (thread-safe lock).
  • Image is preprocessed ONCE and the same array is fed to both models.
  • No demo/fallback mode — if a model file is missing a ModelNotFoundError
    is raised so the caller can return a clear HTTP error to the frontend.
  • Enrichment (treatment, prevention, etc.) is pulled from the existing
    disease_service and a pest knowledge base defined here.

Public API
──────────
  detect_all(image_file, crop_type=None) -> dict

  Returns:
    {
      "disease": {
        "label": str, "confidence": float, "confidence_pct": str,
        "severity": str, "is_healthy": bool, "explanation": str,
        "treatment": str, "fertilizer": str, "prevention": str,
        "organic_option": str, "urgency": str, "crop_note": str
      },
      "pest": {
        "label": str, "confidence": float, "confidence_pct": str,
        "severity": str, "is_healthy": bool, "explanation": str,
        "treatment": str, "prevention": str, "organic_option": str,
        "urgency": str
      }
    }
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

# ── Model paths ───────────────────────────────────────────────────────────────
_MODELS_DIR    = Path(__file__).resolve().parents[1] / "models"
_DISEASE_PATH  = _MODELS_DIR / "disease_model.h5"
_PEST_PATH     = _MODELS_DIR / "pest_model.h5"

# ── Thread-safe lazy model registry ──────────────────────────────────────────
_disease_model = None
_pest_model    = None
_d_lock        = threading.Lock()
_p_lock        = threading.Lock()

# ── Class labels (must match training order) ──────────────────────────────────
_DISEASE_LABELS = ["Leaf Blight", "Powdery Mildew", "Rust", "Healthy"]
_PEST_LABELS    = ["Aphids", "Whiteflies", "Caterpillar", "Healthy"]


class ModelNotFoundError(RuntimeError):
    """Raised when a required model file is absent."""


# ── Model loaders ─────────────────────────────────────────────────────────────

def _load_disease_model():
    global _disease_model
    if _disease_model is not None:
        return _disease_model
    with _d_lock:
        if _disease_model is not None:
            return _disease_model
        if not _DISEASE_PATH.exists():
            raise ModelNotFoundError(
                f"Disease model not found at {_DISEASE_PATH}. "
                "Run:  python models/build_production_model.py"
            )
        from tensorflow.keras.models import load_model as _load
        _disease_model = _load(str(_DISEASE_PATH))
        print(f"[SmartDetector] Disease model loaded  shape={_disease_model.input_shape}")
    return _disease_model


def _load_pest_model():
    global _pest_model
    if _pest_model is not None:
        return _pest_model
    with _p_lock:
        if _pest_model is not None:
            return _pest_model
        if not _PEST_PATH.exists():
            raise ModelNotFoundError(
                f"Pest model not found at {_PEST_PATH}. "
                "Run:  python models/build_pest_model.py"
            )
        from tensorflow.keras.models import load_model as _load
        _pest_model = _load(str(_PEST_PATH))
        print(f"[SmartDetector] Pest model loaded  shape={_pest_model.input_shape}")
    return _pest_model


# ── Preprocessing ─────────────────────────────────────────────────────────────

def _preprocess(image_file) -> np.ndarray:
    """
    Open image, resize to 224×224, normalise to [0, 1].
    Returns a float32 array of shape (1, 224, 224, 3).
    Both models have a Rescaling layer inside that converts [0,1] to [-1,1],
    so this single array can be fed to both without further transformation.
    """
    from PIL import Image
    img = Image.open(image_file).convert("RGB").resize((224, 224))
    arr = np.array(img, dtype="float32") / 255.0
    return np.expand_dims(arr, axis=0)


# ── Pest knowledge base (self-contained — no import from routes) ──────────────
_PEST_KB: dict[str, dict] = {
    "Aphids": {
        "severity":      "Medium",
        "explanation":   "Tiny soft-bodied insects that cluster on new growth and suck plant sap.",
        "treatment":     "Spray neem oil (5 mL/L) or Imidacloprid 17.8 SL (0.5 mL/L) for severe infestation.",
        "prevention":    "Introduce ladybug predators. Avoid excess nitrogen. Use yellow sticky traps.",
        "organic_option":"Diluted neem oil or garlic-chilli spray every 7 days.",
        "urgency":       "Treat within 1 week — colonies double rapidly",
    },
    "Whiteflies": {
        "severity":      "High",
        "explanation":   "Small white flying insects that suck sap and transmit viruses like Leaf Curl.",
        "treatment":     "Apply Thiamethoxam 25 WG (0.3 g/L) or Acetamiprid 20 SP (0.2 g/L).",
        "prevention":    "Yellow sticky traps. Insect-proof netting. Remove alternate weed hosts.",
        "organic_option":"Neem oil (10 mL/L) + mild soap. Reflective silver mulch.",
        "urgency":       "Act within 48 hours — whiteflies spread viruses rapidly",
    },
    "Caterpillar": {
        "severity":      "High",
        "explanation":   "Larval stage of moths/butterflies; stem borers, leaf folders, armyworms.",
        "treatment":     "Chlorpyrifos 20 EC (2 mL/L) or Bt (Bacillus thuringiensis) 2 g/L.",
        "prevention":    "Pheromone traps for monitoring. Encourage parasitic wasps. Crop rotation.",
        "organic_option":"Bt spray is effective and safe. Neem-based feeding deterrents.",
        "urgency":       "Act immediately — caterpillars cause rapid defoliation",
    },
    "Healthy": {
        "severity":      "None",
        "explanation":   "No pest detected. The plant appears pest-free.",
        "treatment":     "No treatment required.",
        "prevention":    "Continue field monitoring every 7-10 days.",
        "organic_option":"No action required.",
        "urgency":       "No immediate action required",
    },
}


# ── Prediction helpers ────────────────────────────────────────────────────────

def _run_model(model, arr: np.ndarray, labels: list[str]) -> tuple[str, float]:
    """Run inference; return (label, confidence_0_to_1)."""
    preds = model.predict(arr, verbose=0)
    idx   = int(np.argmax(preds[0]))
    conf  = float(np.max(preds[0]))
    label = labels[idx] if idx < len(labels) else "Unknown"
    return label, conf


def _enrich_disease(label: str, confidence: float, crop_type: str | None) -> dict:
    """Delegate to the existing disease_service for full enrichment."""
    from services.disease_service import enrich_prediction
    result = enrich_prediction(label, confidence, crop_type=crop_type)
    return result


def _enrich_pest(label: str, confidence: float) -> dict:
    """Build enriched pest result from the local knowledge base."""
    info = _PEST_KB.get(label, {
        "severity":      "Unknown",
        "explanation":   f"Detected: {label}. Consult an agronomist.",
        "treatment":     "Consult your nearest KVK or agriculture officer.",
        "prevention":    "Maintain good field hygiene and monitor regularly.",
        "organic_option":"Neem oil spray (5 mL/L) as a general precaution.",
        "urgency":       "Seek expert advice",
    })
    return {
        "label":           label,
        "confidence":      round(confidence, 4),
        "confidence_pct":  f"{confidence * 100:.1f}%",
        "severity":        info["severity"],
        "is_healthy":      label == "Healthy",
        "explanation":     info["explanation"],
        "treatment":       info["treatment"],
        "prevention":      info["prevention"],
        "organic_option":  info["organic_option"],
        "urgency":         info["urgency"],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def detect_all(image_file, crop_type: str | None = None) -> dict:
    """
    Run disease AND pest detection on the same image.

    Args:
        image_file : A file-like object (e.g. Flask request.files["image"]).
        crop_type  : Optional crop name for crop-specific disease notes.

    Returns:
        {
          "disease": { label, confidence, severity, treatment, ... },
          "pest":    { label, confidence, severity, treatment, ... }
        }

    Raises:
        ModelNotFoundError : If either model file is absent.
        Exception          : If preprocessing or inference fails.
    """
    # Load both models (raises ModelNotFoundError if absent — no demo mode)
    d_model = _load_disease_model()
    p_model = _load_pest_model()

    # Preprocess ONCE — same array fed to both models
    arr = _preprocess(image_file)
    print(f"[SmartDetector] Preprocessed image shape={arr.shape}  dtype={arr.dtype}")

    # Disease inference
    d_label, d_conf = _run_model(d_model, arr, _DISEASE_LABELS)
    print(f"[SmartDetector] Disease -> {d_label} ({d_conf:.0%})")

    # Pest inference
    p_label, p_conf = _run_model(p_model, arr, _PEST_LABELS)
    print(f"[SmartDetector] Pest    -> {p_label} ({p_conf:.0%})")

    return {
        "disease": _enrich_disease(d_label, d_conf, crop_type),
        "pest":    _enrich_pest(p_label, p_conf),
    }

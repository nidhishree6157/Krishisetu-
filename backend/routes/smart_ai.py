"""
routes/smart_ai.py
──────────────────
Smart AI endpoint: POST /smart/analyze

Single image upload → runs BOTH disease detection and pest detection
using real TensorFlow models (no demo fallback).

Blueprint : smart_bp
Prefix    : /smart      (registered in routes/__init__.py)
            Note: /ai prefix is already taken by crop-recommendation routes.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from services.smart_detector import ModelNotFoundError, detect_all
from utils.helpers import json_error, login_required

smart_bp = Blueprint("smart", __name__)


@smart_bp.route("/analyze", methods=["POST"])
@login_required
def analyze():
    """
    POST /smart/analyze
    ─────────────────────
    Form-data fields:
      image      (file, required)
      crop_type  (string, optional) — e.g. "rice", "coconut"

    Response (success):
      {
        "success": true,
        "disease": {
          "label": "Rust",
          "confidence": 0.91,
          "confidence_pct": "91.0%",
          "severity": "High",
          "is_healthy": false,
          "explanation": "...",
          "treatment": "...",
          "fertilizer": "...",
          "prevention": "...",
          "organic_option": "...",
          "urgency": "..."
        },
        "pest": {
          "label": "Aphids",
          "confidence": 0.88,
          "confidence_pct": "88.0%",
          "severity": "Medium",
          "is_healthy": false,
          "explanation": "...",
          "treatment": "...",
          "prevention": "...",
          "organic_option": "...",
          "urgency": "..."
        }
      }
    """
    print(f"[SmartAI] /analyze called  user={session.get('username')}")

    if "image" not in request.files:
        return json_error("image field is required", 400)

    image_file = request.files["image"]
    if not image_file or image_file.filename == "":
        return json_error("No image selected", 400)

    crop_type = (request.form.get("crop_type") or "").strip().lower() or None

    try:
        result = detect_all(image_file, crop_type=crop_type)
    except ModelNotFoundError as exc:
        return json_error(str(exc), 503)
    except Exception as exc:
        print(f"[SmartAI] Unexpected error: {exc}")
        return json_error(f"Detection failed: {exc}", 500)

    return jsonify({
        "success":   True,
        "crop_type": crop_type,
        "disease":   result["disease"],
        "pest":      result["pest"],
    })

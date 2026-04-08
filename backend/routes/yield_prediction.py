"""
routes/yield_prediction.py
──────────────────────────
Yield Prediction API.

Note on filename: "yield" is a Python reserved keyword so the module
is named yield_prediction.py.  The URL prefix is still /yield.

Blueprint : yield_bp
Prefix    : /yield  (registered in routes/__init__.py)
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from services.yield_service import predict_yield
from utils.helpers import json_error, login_required

yield_bp = Blueprint("yield_prediction", __name__)


@yield_bp.post("/predict")
@login_required
def yield_predict():
    """
    POST /yield/predict
    ──────────────────
    Request JSON:
      {
        "crop":        "rice",
        "location":    "karnataka",
        "area":        2.5,
        "rainfall":    120,
        "temperature": 28,
        "soil_type":   "loamy"
      }

    All fields are optional — safe defaults applied when missing.

    Response:
      {
        "success":           true,
        "crop":              "Rice",
        "location":          "karnataka",
        "area_ha":           2.5,
        "yield_prediction":  13000,   // total kg  (yield_per_ha × area)
        "yield_per_hectare": 5200,
        "unit":              "kg",
        "confidence":        0.87,
        "confidence_pct":    "87%",
        "rating":            "Good",
        "advice":            "Good yield expected...",
        "breakdown": { ... }
      }
    """
    data = request.get_json(silent=True) or {}
    print(f"[Yield] /predict  crop={data.get('crop')}  location={data.get('location')}  area={data.get('area')}")

    result = predict_yield(data)

    return jsonify({
        "success":           True,
        # top-level shortcut as specified in the API contract
        "yield_prediction":  result["total_yield"],
        **result,
    }), 200

from __future__ import annotations

import json

import pymysql
from flask import Blueprint, jsonify, request

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
from services.recommendation_service import full_recommendation

recommendation_bp = Blueprint("recommendation", __name__)


def _to_text(value):
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _build_response(result: dict) -> dict:
    """Unified JSON: required keys plus detail fields for dashboards."""
    seeds = result.get("seeds")
    if not isinstance(seeds, list):
        seeds = []
    out = {
        "success": bool(result.get("success")),
        "crop": result.get("crop") if result.get("crop") is not None else "",
        "seeds": seeds,
    }
    if result.get("success"):
        for key in (
            "fertilizer",
            "recommended_crops",
            "seed_recommendations",
            "explanation",
            "weather",
            "location",
            "mode",
        ):
            if key in result:
                out[key] = result[key]
    else:
        if result.get("message"):
            out["message"] = result["message"]
        if result.get("detail"):
            out["detail"] = result["detail"]
    return out


@recommendation_bp.post("/recommend")
def recommend_route():
    """POST /api/recommend — unified crop + seed recommendation."""
    user_id = 1

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}

    raw_mode = payload.get("mode")
    if raw_mode is None or (isinstance(raw_mode, str) and not raw_mode.strip()):
        return (
            jsonify(
                {
                    "success": False,
                    "crop": "",
                    "seeds": [],
                    "message": "mode is required",
                }
            ),
            400,
        )

    mode = str(raw_mode).strip().lower()

    try:
        conn_ctx = get_db_connection()
        _fid = resolve_farmer_id(conn_ctx)
        _farmer = fetch_farmer_row(conn_ctx, _fid)
        _soil = fetch_soil_row(conn_ctx, _fid)
        merge_farmer_profile_into_payload(payload, _farmer)
        merge_soil_into_payload(payload, _soil)
    except DBConnectionError:
        pass

    if mode in ("new", "existing") and not payload_has_soil_values(payload):
        return (
            jsonify(
                {
                    "success": False,
                    "crop": "",
                    "seeds": [],
                    "message": SOIL_MESSAGE,
                }
            ),
            400,
        )

    data = {**payload, "user_id": user_id, "mode": mode}

    try:
        result = full_recommendation(data)
    except (TypeError, ValueError) as e:
        return (
            jsonify(
                {
                    "success": False,
                    "crop": "",
                    "seeds": [],
                    "message": "Invalid input",
                    "detail": str(e),
                }
            ),
            400,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "success": False,
                    "crop": "",
                    "seeds": [],
                    "message": "Recommendation failed",
                    "detail": str(e),
                }
            ),
            500,
        )

    if not result.get("success"):
        return jsonify(_build_response(result)), 400

    crop = result.get("crop")
    crop_str = crop if crop is None else str(crop)[:50]
    loc = result.get("location")
    loc_str = loc if loc is None else str(loc)[:100]
    mode_str = result.get("mode")
    mode_out = mode_str if mode_str is None else str(mode_str)[:20]

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO recommendations (user_id, crop, seeds, fertilizer, location, mode)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    crop_str,
                    _to_text(result.get("seeds")),
                    _to_text(result.get("fertilizer")),
                    loc_str,
                    mode_out,
                ),
            )
        conn.commit()
    except DBConnectionError:
        return (
            jsonify(
                {
                    "success": False,
                    "crop": "",
                    "seeds": [],
                    "message": "DB connection failed",
                }
            ),
            500,
        )
    except pymysql.MySQLError:
        return (
            jsonify(
                {
                    "success": False,
                    "crop": "",
                    "seeds": [],
                    "message": "Failed to save recommendation",
                }
            ),
            500,
        )

    return jsonify(_build_response(result)), 200

from flask import Blueprint, jsonify, request
import pymysql

from db import DBConnectionError, get_db_connection
from services.schemes_service import get_schemes
from services.profit_service import calculate_profit
from utils.helpers import json_error, json_ok, role_required, login_required


schemes_bp = Blueprint("schemes", __name__)


# ── Scheme Intelligence endpoint ─────────────────────────────────────────────

@schemes_bp.get("/recommend")
def recommend_schemes():
    """
    GET /schemes/recommend?crop=rice&location=karnataka

    Returns applicable national + state schemes for the given crop and location.
    No auth required — purely informational.
    """
    crop     = (request.args.get("crop")     or "").strip()
    location = (request.args.get("location") or "").strip()

    schemes = get_schemes(crop, location)
    return jsonify({"success": True, "schemes": schemes, "count": len(schemes)}), 200


# ── Profit Intelligence endpoint ──────────────────────────────────────────────

@schemes_bp.post("/profit")
def profit_calculator():
    """
    POST /schemes/profit
    Body JSON:
      {
        "yield_kg":          5200,
        "price_per_quintal": 2200,
        "cost":              18000,
        "area_ha":           2.5
      }

    Calculates revenue, profit, margin, and breakeven price.
    """
    data              = request.get_json(silent=True) or {}
    yield_kg          = data.get("yield_kg")          or data.get("yield")
    price_per_quintal = data.get("price_per_quintal") or data.get("price")
    cost              = data.get("cost")
    area_ha           = data.get("area_ha")            or data.get("area") or 1.0

    if yield_kg is None or price_per_quintal is None or cost is None:
        return json_error("yield_kg, price_per_quintal and cost are required", 400)

    result = calculate_profit(yield_kg, price_per_quintal, cost, area_ha)
    return jsonify({"success": True, **result}), 200


@schemes_bp.post("/add")
def add_scheme():
    data = request.get_json(silent=True) or {}

    scheme_name = str(data.get("scheme_name") or "").strip()
    description = str(data.get("description") or "").strip()
    eligibility = str(data.get("eligibility") or "").strip()
    last_date = str(data.get("last_date") or "").strip()

    missing = []
    if not scheme_name:
        missing.append("scheme_name")
    if not description:
        missing.append("description")
    if not eligibility:
        missing.append("eligibility")
    if not last_date:
        missing.append("last_date")

    if missing:
        return json_error("Missing required fields", 400, missing=missing)

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO government_schemes (scheme_name, description, eligibility, last_date)
                VALUES (%s, %s, %s, %s)
                """,
                (scheme_name, description, eligibility, last_date),
            )

        return json_ok("Scheme added", 201)
    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))


@schemes_bp.get("/all")
@login_required
@role_required("Farmer")
def all_schemes():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT scheme_id, scheme_name, description, eligibility, last_date
                FROM government_schemes
                ORDER BY last_date DESC
                """
            )
            rows = cur.fetchall()

        return jsonify({"success": True, "data": rows}), 200
    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))


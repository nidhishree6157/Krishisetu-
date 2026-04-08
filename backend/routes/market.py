from flask import Blueprint, jsonify, request
import pymysql
import requests

from db import DBConnectionError, get_db_connection
from services.market_service import get_market_data
from utils.helpers import json_error


market_bp = Blueprint("market", __name__)


# ── Market Intelligence endpoint (service-backed, always returns data) ────────

@market_bp.get("/intelligence")
def market_intelligence():
    """
    GET /market/intelligence?crop=rice&location=karnataka

    Uses the market_service layer: tries the real API first, falls back
    to realistic simulated data.  Never returns an error — always 200.
    """
    crop     = (request.args.get("crop") or "rice").strip()
    location = (request.args.get("location") or "karnataka").strip()

    data = get_market_data(crop, location)
    return jsonify({"success": True, "data": data}), 200

API_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
RESOURCE_ID = "35985678-0d79-46b4-9ed6-6f13308a1d24"


def _to_float(value):
    try:
        return float(value)
    except Exception:
        return None


@market_bp.post("/add")
def add_market_price():
    data = request.get_json(silent=True) or {}
    crop_name = str(data.get("crop_name") or "").strip()
    market_location = str(data.get("market_location") or "").strip()
    price_raw = data.get("price")

    missing = []
    if not crop_name:
        missing.append("crop_name")
    if not market_location:
        missing.append("market_location")
    if price_raw is None or price_raw == "":
        missing.append("price")
    if missing:
        return json_error("Missing required fields", 400, missing=missing)

    price = _to_float(price_raw)
    if price is None:
        return json_error("Invalid price; must be numeric", 400)

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_prices (crop_name, market_location, price, price_date)
                VALUES (%s, %s, %s, NOW())
                """,
                (crop_name, market_location, price),
            )
        
        conn.commit()
        return jsonify({"success": True, "message": "Market price added"}), 201
    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))


@market_bp.get("/prices")
def get_market_prices():
    crop_name = str(
        request.args.get("crop") or
        request.args.get("crop_name") or "").strip()
    if not crop_name:
        return jsonify({"success": False, "source": "backend", "data": [], "message": "crop parameter is required"}), 400

    # 1) Try external API first
    try:
        url = (
            f"https://api.data.gov.in/resource/{RESOURCE_ID}"
            f"?api-key={API_KEY}&format=json&filters[commodity]={crop_name.capitalize()}"
        )
        response = requests.get(url, timeout=12)
        if response.status_code == 200:
            records = (response.json() or {}).get("records", []) or []
            parsed_data = []
            for item in records:
                parsed_data.append(
                    {
                        "crop_name": item.get("commodity"),
                        "market": item.get("market"),
                        "price": item.get("modal_price") or item.get("min_price"),
                    }
                )
            if parsed_data:
                return jsonify({"success": True, "source": "api", "data": parsed_data}), 200
    except Exception:
        # Explicit fallback to DB on any API error
        pass

    # 2) Fallback to existing DB logic
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT price_id, crop_name, market_location, price, price_date
                FROM market_prices
                WHERE crop_name=%s
                ORDER BY price_date DESC
                """,
                (crop_name,),
            )
            rows = cur.fetchall()

        return jsonify({"success": True, "source": "database", "data": rows}), 200
    except DBConnectionError as e:
        return jsonify({"success": False, "source": "database", "data": [], "message": "DB connection failed"}), 500
    except pymysql.MySQLError as e:
        return jsonify({"success": False, "source": "database", "data": [], "message": "Database operation failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "source": "database", "data": [], "message": "Unexpected error"}), 500


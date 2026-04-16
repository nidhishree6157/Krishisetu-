"""
routes/soil.py
──────────────
Soil data — single source of truth: the `soil_data` table.

POST /soil/data   →  upsert soil values, then sync to farmers columns
GET  /soil/data   →  return latest soil values for the current farmer

Column naming
─────────────
  DB has both `soil_ph` (original) and `ph` (added by migration in db.py).
  This module always writes BOTH, and all API responses use the key `ph`.

Sync
────
  Every successful upsert mirrors values into `farmers` (nitrogen,
  phosphorus, potassium, ph) so profile/crop/AI routes stay consistent.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from db import DBConnectionError, get_db_connection
from utils.helpers import json_error, json_ok, login_required, role_required


soil_bp = Blueprint("soil", __name__)


def farmer_required(fn):
    return role_required("Farmer")(login_required(fn))


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_username() -> str | None:
    return session.get("username") or None


def _get_farmer_id_for_user(conn, username: str) -> int | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1",
                (username,),
            )
            row = cur.fetchone()
            return int(row["farmer_id"]) if row else None
    except Exception:
        return None


def _ph_from_row(row: dict | None) -> float | None:
    """Return pH, preferring new `ph` column over legacy `soil_ph`."""
    if row is None:
        return None
    v = row.get("ph")
    if v is None:
        v = row.get("soil_ph")
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _upsert_soil_data(conn, farmer_id: int,
                      nitrogen: float, phosphorus: float,
                      potassium: float, ph: float,
                      organic_carbon: float = 0.0) -> None:
    """Insert or update soil_data for *farmer_id*, writing both ph columns."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM soil_data WHERE farmer_id=%s LIMIT 1",
            (farmer_id,),
        )
        if cur.fetchone():
            cur.execute(
                """
                UPDATE soil_data
                SET    nitrogen=%s, phosphorus=%s, potassium=%s,
                       soil_ph=%s, ph=%s, organic_carbon=%s,
                       created_at=NOW()
                WHERE  farmer_id=%s
                """,
                (nitrogen, phosphorus, potassium, ph, ph, organic_carbon, farmer_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO soil_data
                  (farmer_id, nitrogen, phosphorus, potassium,
                   soil_ph, ph, organic_carbon, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (farmer_id, nitrogen, phosphorus, potassium, ph, ph, organic_carbon),
            )


def _sync_to_farmers(conn, username: str,
                     nitrogen: float, phosphorus: float,
                     potassium: float, ph: float) -> None:
    """Mirror soil values into farmers table — best-effort, never raises."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE farmers
                SET nitrogen=%s, phosphorus=%s, potassium=%s, ph=%s
                WHERE username=%s
                """,
                (nitrogen, phosphorus, potassium, ph, username),
            )
    except Exception as exc:
        print(f"[Soil] Sync to farmers failed (non-fatal): {exc}")


# ── POST /soil/data ───────────────────────────────────────────────────────────

@soil_bp.post("/data")
def upsert_soil_data():
    data = request.get_json(silent=True) or {}

    print("Incoming data:", data)

    nitrogen       = float(data.get("nitrogen", 0))
    phosphorus     = float(data.get("phosphorus", 0))
    potassium      = float(data.get("potassium", 0))
    ph             = float(data.get("ph", 0))
    organic_matter = float(data.get("organic_matter", 0))
    ec             = float(data.get("electrical_conductivity") or data.get("ec") or 0)
    location       = data.get("location", "")
    soil_type      = data.get("soil_type", "")
    email          = data.get("email")

    try:
        conn = get_db_connection()

        username = _get_username()

        if not username:
            if email:
                with conn.cursor() as cur:
                    cur.execute("SELECT username FROM users WHERE email=%s", (email,))
                    row = cur.fetchone()
                    if row:
                        username = row["username"]

        if not username:
            return jsonify({"success": False, "message": "User not found"}), 404

        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE farmers SET
                  nitrogen=%s,
                  phosphorus=%s,
                  potassium=%s,
                  ph=%s,
                  organic_matter=%s,
                  electrical_conductivity=%s,
                  location=%s,
                  soil_type=%s
                WHERE username=%s
                """,
                (
                    nitrogen, phosphorus, potassium, ph,
                    organic_matter, ec,
                    location, soil_type,
                    username,
                ),
            )

        conn.commit()

        return jsonify({"success": True, "message": "Soil data saved successfully"})

    except Exception as e:
        print("SOIL ERROR:", e)
        return jsonify({"success": False, "message": str(e)}), 500


# ── GET /soil/data ────────────────────────────────────────────────────────────

@soil_bp.get("/data")
@farmer_required
def get_soil_data():
    """Return latest soil data for the current farmer. Always uses key `ph`."""
    username = _get_username()
    if not username:
        return json_error("Authentication required", 401)

    try:
        conn      = get_db_connection()
        farmer_id = _get_farmer_id_for_user(conn, username)
        if farmer_id is None:
            return json_error("Please create your farmer profile first", 400)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nitrogen, phosphorus, potassium,
                       soil_ph, ph, organic_carbon, created_at
                FROM   soil_data
                WHERE  farmer_id = %s
                LIMIT  1
                """,
                (farmer_id,),
            )
            row = cur.fetchone()

        if not row:
            return json_error("No soil data on file", 404,
                              error="SOIL_DATA_NOT_FOUND")

        return json_ok("Soil data fetched", 200, data={
            "farmer_id":      farmer_id,
            "nitrogen":       row.get("nitrogen"),
            "phosphorus":     row.get("phosphorus"),
            "potassium":      row.get("potassium"),
            "ph":             _ph_from_row(row),
            "organic_carbon": row.get("organic_carbon"),
            "created_at":     str(row["created_at"]) if row.get("created_at") else None,
        })

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except Exception as exc:
        print(f"[Soil] GET failed: {exc}")
        return json_error("Database operation failed", 500)


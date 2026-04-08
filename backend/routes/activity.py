from __future__ import annotations

from datetime import datetime

import pymysql
from flask import Blueprint, jsonify, request, session

from db import DBConnectionError, get_db_connection
from utils.helpers import json_error, json_ok, login_required, role_required


activity_bp = Blueprint("activity", __name__)


def farmer_required(fn):
    return role_required("Farmer")(login_required(fn))


def _validate_date(value: str) -> bool:
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except Exception:
        return False


def _get_farmer_id(conn, username: str):
    with conn.cursor() as cur:
        cur.execute("SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1", (username,))
        row = cur.fetchone()
        return None if not row else row.get("farmer_id")


@activity_bp.post("/add")
@farmer_required
def add_activity():
    payload = request.get_json(silent=True) or {}
    activity_type = str(payload.get("activity_type") or "").strip()
    activity_date = str(payload.get("activity_date") or "").strip()
    reminder = str(payload.get("reminder") or "").strip()

    if not activity_type:
        return json_error("activity_type is required", 400)
    if not activity_date:
        return json_error("activity_date is required", 400)
    if not _validate_date(activity_date):
        return json_error("activity_date must be in YYYY-MM-DD format", 400)

    username = session.get("username")
    if not username:
        return json_error("Authentication required", 401)

    try:
        conn = get_db_connection()
        farmer_id = _get_farmer_id(conn, username)
        if not farmer_id:
            return jsonify({"success": False, "message": "Please create farmer profile first"}), 400

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO activity_schedule (farmer_id, activity_type, activity_date, reminder)
                VALUES (%s, %s, %s, %s)
                """,
                (farmer_id, activity_type, activity_date, reminder),
            )
        return json_ok("Activity added", 200)
    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError:
        return json_error("Database operation failed", 500)
    except Exception:
        return json_error("Unexpected error", 500)


@activity_bp.get("/list")
@farmer_required
def list_activities():
    username = session.get("username")
    if not username:
        return json_error("Authentication required", 401)

    try:
        conn = get_db_connection()
        farmer_id = _get_farmer_id(conn, username)
        if not farmer_id:
            return jsonify({"success": False, "message": "Please create farmer profile first"}), 400

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schedule_id, farmer_id, activity_type, activity_date, reminder
                FROM activity_schedule
                WHERE farmer_id=%s
                ORDER BY activity_date ASC, schedule_id DESC
                """,
                (farmer_id,),
            )
            rows = cur.fetchall() or []
        return json_ok("Activities fetched", 200, activities=rows)
    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError:
        return json_error("Database operation failed", 500)
    except Exception:
        return json_error("Unexpected error", 500)


@activity_bp.delete("/delete/<int:schedule_id>")
@farmer_required
def delete_activity(schedule_id: int):
    username = session.get("username")
    if not username:
        return json_error("Authentication required", 401)

    try:
        conn = get_db_connection()
        farmer_id = _get_farmer_id(conn, username)
        if not farmer_id:
            return jsonify({"success": False, "message": "Please create farmer profile first"}), 400

        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM activity_schedule
                WHERE schedule_id=%s AND farmer_id=%s
                """,
                (schedule_id, farmer_id),
            )
            if cur.rowcount == 0:
                return json_error("Activity not found", 404)
        return json_ok("Activity deleted", 200)
    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError:
        return json_error("Database operation failed", 500)
    except Exception:
        return json_error("Unexpected error", 500)


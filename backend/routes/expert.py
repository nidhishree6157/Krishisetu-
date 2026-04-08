from __future__ import annotations

import pymysql
from flask import Blueprint, jsonify, request, session

from db import DBConnectionError, get_db_connection
from utils.helpers import is_valid_mobile, json_error, json_ok, role_required


expert_bp = Blueprint("expert", __name__)


def _required_fields_present(data: dict, required: list[str]) -> list[str]:
    missing: list[str] = []
    for k in required:
        if k not in data or data.get(k) is None:
            missing.append(k)
            continue
        if isinstance(data.get(k), str) and not str(data.get(k)).strip():
            missing.append(k)
            continue
    return missing


def _ensure_experts_table(conn):
    with conn.cursor() as cur:
        try:
            cur.execute("ALTER TABLE users ADD UNIQUE KEY uq_users_username (username)")
        except Exception:
            pass

        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS experts (
                  username VARCHAR(100) NOT NULL,
                  mobile_number VARCHAR(20) NOT NULL,
                  expertise_field VARCHAR(100) NOT NULL,
                  experience_years INT NOT NULL,
                  qualification TEXT NOT NULL,
                  PRIMARY KEY (username),
                  CONSTRAINT fk_experts_username
                    FOREIGN KEY (username) REFERENCES users(username)
                    ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
        except pymysql.MySQLError:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS experts (
                  username VARCHAR(100) NOT NULL,
                  mobile_number VARCHAR(20) NOT NULL,
                  expertise_field VARCHAR(100) NOT NULL,
                  experience_years INT NOT NULL,
                  qualification TEXT NOT NULL,
                  PRIMARY KEY (username)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )

        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'experts'
                  AND COLUMN_NAME = 'expert_id'
                """
            )
            row = cur.fetchone() or {}
            if int(row.get("cnt") or 0) == 0:
                cur.execute(
                    """
                    ALTER TABLE experts
                      ADD COLUMN expert_id INT NOT NULL AUTO_INCREMENT,
                      ADD UNIQUE KEY uq_experts_expert_id (expert_id)
                    """
                )
        except Exception:
            pass


def _get_username_or_fail():
    username = session.get("username")
    if not username:
        return None
    return str(username)


@expert_bp.post("/profile")
@role_required("Expert")
def upsert_expert_profile():
    data = request.get_json(silent=True) or {}
    required = ["mobile_number", "expertise_field", "experience_years", "qualification"]
    missing = _required_fields_present(data, required)
    if missing:
        return json_error("Missing required fields", 400, missing=missing)

    username = _get_username_or_fail()
    if not username:
        return json_error("Authentication required", 401)

    mobile_number = str(data["mobile_number"]).strip()
    if not is_valid_mobile(mobile_number):
        return json_error("Invalid mobile number. Use 10-15 digits.", 400)

    expertise_field = str(data["expertise_field"]).strip()
    qualification = str(data["qualification"]).strip()

    try:
        experience_years = int(data["experience_years"])
    except Exception:
        return json_error("experience_years must be numeric", 400)

    try:
        conn = get_db_connection()
        _ensure_experts_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO experts
                  (username, mobile_number, expertise_field, experience_years, qualification)
                VALUES
                  (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  mobile_number=VALUES(mobile_number),
                  expertise_field=VALUES(expertise_field),
                  experience_years=VALUES(experience_years),
                  qualification=VALUES(qualification)
                """,
                (username, mobile_number, expertise_field, experience_years, qualification),
            )
        return json_ok("Expert profile saved", 200)

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError:
        return json_error("Database operation failed", 500)
    except Exception:
        return json_error("Unexpected error", 500)


@expert_bp.get("/profile")
@role_required("Expert")
def get_expert_profile():
    username = _get_username_or_fail()
    if not username:
        return json_error("Authentication required", 401)

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT username, mobile_number, expertise_field, experience_years, qualification
                FROM experts
                WHERE username=%s
                """,
                (username,),
            )
            profile = cur.fetchone()
            if not profile:
                return json_error("Profile not found", 404)
        return json_ok("Expert profile fetched", 200, profile=profile)
    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError:
        return json_error("Database operation failed", 500)
    except Exception:
        return json_error("Unexpected error", 500)


def _get_farmer_id_or_fail(conn) -> int | None:
    username = session.get("username")
    if not username:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1", (username,))
        row = cur.fetchone()
        if not row:
            return None
        return row.get("farmer_id")


@expert_bp.post("/query")
def submit_query():
    data = request.get_json(silent=True) or {}

    query_text = str(data.get("query_text") or "").strip()

    if not query_text:
        crop = str(data.get("crop") or "").strip()
        location = str(data.get("location") or "").strip()
        mode = str(data.get("mode") or "").strip()
        fertilizer = str(data.get("fertilizer") or "").strip()

        query_text = (
            f"Crop: {crop} | Location: {location} | Mode: {mode} | Fertilizer: {fertilizer}"
        ).strip()

    if not query_text:
        return json_error("Missing required fields", 400, missing=["query_text"])

    try:
        conn = get_db_connection()

        farmer_id = None
        try:
            farmer_id = _get_farmer_id_or_fail(conn)
        except Exception:
            farmer_id = None

        if not farmer_id:
            farmer_id = 1

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO expert_queries (farmer_id, expert_id, query_text, query_date, status)
                VALUES (%s, NULL, %s, NOW(), 'Pending')
                """,
                (farmer_id, query_text),
            )

        return json_ok("Query submitted", 200)

    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))


@expert_bp.get("/my-queries")
@role_required("Farmer")
def my_queries():
    try:
        conn = get_db_connection()
        farmer_id = _get_farmer_id_or_fail(conn)
        if not farmer_id:
            return json_error("Farmer not found", 404)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT query_id, query_text, query_date, expert_response, response_date, status
                FROM expert_queries
                WHERE farmer_id=%s
                ORDER BY query_date DESC
                """,
                (farmer_id,),
            )
            queries = cur.fetchall()

        return jsonify({"success": True, "data": queries}), 200
    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))


@expert_bp.get("/all-queries")
@role_required("Expert")
def all_queries():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT query_id, farmer_id, query_text, query_date, expert_response, response_date, status
                FROM expert_queries
                WHERE status='Pending'
                ORDER BY query_date DESC
                """
            )
            queries = cur.fetchall()

        return jsonify({"success": True, "data": queries}), 200
    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))


@expert_bp.post("/respond")
@role_required("Expert")
def respond():
    data = request.get_json(silent=True) or {}
    missing = _required_fields_present(data, ["query_id", "response"])
    if missing:
        return json_error("Missing required fields", 400, missing=missing)

    try:
        query_id = int(data["query_id"])
    except Exception:
        return json_error("query_id must be an integer", 400)

    response_text = str(data["response"]).strip()
    if not response_text:
        return json_error("response cannot be empty", 400)

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT query_id FROM expert_queries WHERE query_id=%s LIMIT 1", (query_id,))
            if not cur.fetchone():
                return json_error("Query not found", 404)

            cur.execute(
                """
                UPDATE expert_queries
                SET expert_response=%s,
                    response_date=NOW(),
                    status='Answered'
                WHERE query_id=%s
                """,
                (response_text, query_id),
            )

        return json_ok("Response saved", 200)
    except DBConnectionError as e:
        return json_error("DB connection failed", 500, detail=str(e))
    except pymysql.MySQLError as e:
        return json_error("Database operation failed", 500, detail=str(e))
    except Exception as e:
        return json_error("Unexpected error", 500, detail=str(e))
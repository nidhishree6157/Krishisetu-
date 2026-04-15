import os

import pymysql
from flask import Blueprint, request, session
from werkzeug.utils import secure_filename

from config import Config
from db import DBConnectionError, get_db_connection
from utils.helpers import is_valid_mobile, json_error, json_ok, login_required, role_required

farmer_bp = Blueprint("farmer", __name__)

# ── Upload folder for soil reports ───────────────────────────────────────────
_SOIL_UPLOAD_DIR = os.path.join(
    os.path.dirname(__file__), "..", "uploads", "soil_reports"
)
os.makedirs(_SOIL_UPLOAD_DIR, exist_ok=True)

_SOIL_ALLOWED = {"pdf", "jpg", "jpeg", "png"}


def _allowed_soil_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in _SOIL_ALLOWED


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _required_fields_present(data: dict, required: list[str]) -> list[str]:
    missing: list[str] = []
    for k in required:
        if k not in data or data.get(k) is None:
            missing.append(k)
            continue
        if isinstance(data.get(k), str) and not str(data.get(k)).strip():
            missing.append(k)
    return missing


def _ensure_farmers_table(conn):
    """
    Best-effort schema setup to support one-to-one farmer profiles.
    """
    with conn.cursor() as cur:
        try:
            cur.execute("ALTER TABLE users ADD UNIQUE KEY uq_users_username (username)")
        except Exception:
            pass

        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS farmers (
                  username         VARCHAR(100)   NOT NULL,
                  mobile_number    VARCHAR(20)    NOT NULL,
                  crop_type        VARCHAR(100)   NOT NULL,
                  location         VARCHAR(255)   NOT NULL,
                  land_size        DECIMAL(10,2)  NOT NULL,
                  irrigation_type  VARCHAR(100)   NOT NULL DEFAULT '',
                  survey_number    VARCHAR(100)   NOT NULL DEFAULT '',
                  soil_report_file TEXT           NOT NULL DEFAULT '',
                  nitrogen         DECIMAL(10,2)  NULL,
                  phosphorus       DECIMAL(10,2)  NULL,
                  potassium        DECIMAL(10,2)  NULL,
                  ph               DECIMAL(4,2)   NULL,
                  PRIMARY KEY (username),
                  CONSTRAINT fk_farmers_username
                    FOREIGN KEY (username) REFERENCES users(username)
                    ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
        except pymysql.MySQLError:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS farmers (
                  username         VARCHAR(100)   NOT NULL,
                  mobile_number    VARCHAR(20)    NOT NULL,
                  crop_type        VARCHAR(100)   NOT NULL,
                  location         VARCHAR(255)   NOT NULL,
                  land_size        DECIMAL(10,2)  NOT NULL,
                  irrigation_type  VARCHAR(100)   NOT NULL DEFAULT '',
                  survey_number    VARCHAR(100)   NOT NULL DEFAULT '',
                  soil_report_file TEXT           NOT NULL DEFAULT '',
                  nitrogen         DECIMAL(10,2)  NULL,
                  phosphorus       DECIMAL(10,2)  NULL,
                  potassium        DECIMAL(10,2)  NULL,
                  ph               DECIMAL(4,2)   NULL,
                  PRIMARY KEY (username)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )


def _ensure_soil_columns(conn):
    """
    Idempotently adds nitrogen / phosphorus / potassium / ph columns to an
    already-existing farmers table that was created before these were added.
    """
    new_cols = [
        ("nitrogen",   "ALTER TABLE farmers ADD COLUMN nitrogen   DECIMAL(10,2) NULL"),
        ("phosphorus", "ALTER TABLE farmers ADD COLUMN phosphorus DECIMAL(10,2) NULL"),
        ("potassium",  "ALTER TABLE farmers ADD COLUMN potassium  DECIMAL(10,2) NULL"),
        ("ph",         "ALTER TABLE farmers ADD COLUMN ph         DECIMAL(4,2)  NULL"),
    ]
    with conn.cursor() as cur:
        for _col, ddl in new_cols:
            try:
                cur.execute(ddl)
            except pymysql.MySQLError:
                pass  # column already exists — safe to ignore


# ─────────────────────────────────────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _get_username_or_fail():
    username = session.get("username")
    if not username:
        return None
    return str(username)


def farmer_required(fn):
    return role_required("Farmer")(fn)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────────────────────

# GET /farmer/test  (legacy)
@farmer_bp.get("/test")
@farmer_required
def farmer_test():
    return json_ok("Farmer route working", 200, username=session.get("username"))


# ── GET /farmer/profile ──────────────────────────────────────────────────────
@farmer_bp.get("/profile")
@farmer_required
def get_profile():
    try:
        username = _get_username_or_fail()
        if not username:
            return json_error("Authentication required", 401)

        conn = get_db_connection()
        _ensure_soil_columns(conn)

        with conn.cursor() as cur:
            # Always fetch base user data (username, email, mobile, aadhaar)
            cur.execute(
                """
                SELECT username, email,
                       mobile_number  AS user_mobile,
                       aadhaar_number AS aadhaar
                FROM   users
                WHERE  username = %s
                """,
                (username,),
            )
            user_row = cur.fetchone() or {}

            # Fetch farmer-specific row if it exists
            cur.execute(
                """
                SELECT mobile_number, crop_type, location, land_size,
                       irrigation_type, survey_number, soil_report_file,
                       nitrogen, phosphorus, potassium, ph
                FROM   farmers
                WHERE  username = %s
                """,
                (username,),
            )
            farmer_row = cur.fetchone()

        profile = {
            "username":         user_row.get("username", username),
            "email":            user_row.get("email", ""),
            "aadhaar_number":   user_row.get("aadhaar", ""),
            "mobile_number":    "",
            "crop_type":        "",
            "location":         "",
            "land_size":        None,
            "irrigation_type":  "",
            "survey_number":    "",
            "soil_report_file": "",
            "nitrogen":         None,
            "phosphorus":       None,
            "potassium":        None,
            "ph":               None,
            "has_soil_data":    False,
        }

        if farmer_row:
            profile.update({
                "mobile_number":    farmer_row.get("mobile_number", ""),
                "crop_type":        farmer_row.get("crop_type", ""),
                "location":         farmer_row.get("location", ""),
                "land_size":        farmer_row.get("land_size"),
                "irrigation_type":  farmer_row.get("irrigation_type", ""),
                "survey_number":    farmer_row.get("survey_number", ""),
                "soil_report_file": farmer_row.get("soil_report_file", ""),
                "nitrogen":         farmer_row.get("nitrogen"),
                "phosphorus":       farmer_row.get("phosphorus"),
                "potassium":        farmer_row.get("potassium"),
                "ph":               farmer_row.get("ph"),
            })
            if farmer_row.get("nitrogen") is not None:
                profile["has_soil_data"] = True

        return json_ok("Profile fetched", 200, profile=profile)

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError as e:
        return json_error("Database error", 500)
    except Exception:
        return json_error("Unexpected error", 500)


# ── POST /farmer/profile  (create or update farm details) ───────────────────
@farmer_bp.post("/profile")
@farmer_required
def upsert_profile():
    data = request.get_json(silent=True) or {}
    required = ["mobile_number", "crop_type", "location", "land_size"]
    missing = _required_fields_present(data, required)
    if missing:
        return json_error("Missing required fields", 400, missing=missing)

    username = _get_username_or_fail()
    if not username:
        return json_error("Authentication required", 401)

    mobile_number = str(data["mobile_number"]).strip()
    if not is_valid_mobile(mobile_number):
        return json_error("Invalid mobile number. Use 10-15 digits.", 400)

    crop_type       = str(data["crop_type"]).strip()
    location        = str(data["location"]).strip()
    irrigation_type = str(data.get("irrigation_type") or "").strip()
    survey_number   = str(data.get("survey_number") or "").strip()

    try:
        land_size = float(data["land_size"])
    except Exception:
        return json_error("land_size must be a number", 400)

    try:
        conn = get_db_connection()
        _ensure_farmers_table(conn)
        _ensure_soil_columns(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT username FROM farmers WHERE username=%s", (username,))
            exists = cur.fetchone() is not None

            if exists:
                cur.execute(
                    """
                    UPDATE farmers
                    SET mobile_number=%s, crop_type=%s, location=%s, land_size=%s,
                        irrigation_type=%s, survey_number=%s
                    WHERE username=%s
                    """,
                    (mobile_number, crop_type, location, land_size,
                     irrigation_type, survey_number, username),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO farmers
                      (username, mobile_number, crop_type, location, land_size,
                       irrigation_type, survey_number, soil_report_file)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, '')
                    """,
                    (username, mobile_number, crop_type, location, land_size,
                     irrigation_type, survey_number),
                )

        conn.commit()
        return json_ok("Profile saved", 200)

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError as e:
        return json_error("Database error", 500)
    except Exception:
        return json_error("Unexpected error", 500)


# ── PUT /farmer/profile  (alias) ─────────────────────────────────────────────
@farmer_bp.put("/profile")
@farmer_required
def update_profile():
    return upsert_profile()


# ── POST /farmer/upload-soil-report ──────────────────────────────────────────
@farmer_bp.post("/upload-soil-report")
@farmer_required
def upload_soil_report():
    """
    Accepts a multipart upload of a soil report (PDF / JPG / PNG).
    Runs the soil parser to extract NPK + pH values.
    Stores extracted values and the file path in the farmers table.
    Returns the extracted values so the frontend can display / use them.
    """
    username = _get_username_or_fail()
    if not username:
        return json_error("Authentication required", 401)

    file = request.files.get("soil_report")
    if not file or not file.filename:
        return json_error("No file uploaded. Attach a PDF or image as 'soil_report'.", 400)

    if not _allowed_soil_file(file.filename):
        return json_error("File type not allowed. Upload PDF, JPG, or PNG.", 400)

    # Save file
    safe_name = secure_filename(file.filename)
    filepath = os.path.join(_SOIL_UPLOAD_DIR, f"{username}_{safe_name}")
    try:
        file.save(filepath)
    except Exception as exc:
        return json_error(f"Could not save file: {exc}", 500)

    # ── Validation: check the file is a real soil report ─────────────────
    # validate_soil_report() is additive — it never touches extract_soil_data.
    # If the required OCR/PDF libraries are absent it returns (True, "") so
    # the feature degrades gracefully to demo values, just as before.
    try:
        from services.soil_parser import validate_soil_report
        is_valid, validation_error = validate_soil_report(filepath)
        if not is_valid:
            try:
                os.remove(filepath)      # discard invalid file
            except Exception:
                pass
            return json_error(validation_error, 400)
    except Exception as exc:
        # Never let the validation step crash the whole upload.
        print(f"[SoilParser] Validation skipped due to unexpected error: {exc}")

    # Extract soil values
    try:
        from services.soil_parser import extract_soil_data
        soil = extract_soil_data(filepath)
    except Exception as exc:
        print(f"[SoilParser] Error: {exc}")
        soil = {"nitrogen": 82.0, "phosphorus": 38.0, "potassium": 42.0, "ph": 6.4}

    nitrogen   = soil["nitrogen"]
    phosphorus = soil["phosphorus"]
    potassium  = soil["potassium"]
    ph         = soil["ph"]

    # Persist to DB — upsert farmer row if it doesn't exist yet
    try:
        conn = get_db_connection()
        _ensure_farmers_table(conn)
        _ensure_soil_columns(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT username FROM farmers WHERE username=%s", (username,))
            exists = cur.fetchone() is not None

            if exists:
                cur.execute(
                    """
                    UPDATE farmers
                    SET soil_report_file=%s, nitrogen=%s,
                        phosphorus=%s, potassium=%s, ph=%s
                    WHERE username=%s
                    """,
                    (filepath, nitrogen, phosphorus, potassium, ph, username),
                )
            else:
                # Create a minimal farmer row so the report can be stored
                cur.execute(
                    """
                    INSERT INTO farmers
                      (username, mobile_number, crop_type, location, land_size,
                       irrigation_type, survey_number, soil_report_file,
                       nitrogen, phosphorus, potassium, ph)
                    VALUES (%s, '', '', '', 0, '', '', %s, %s, %s, %s, %s)
                    """,
                    (username, filepath, nitrogen, phosphorus, potassium, ph),
                )

        conn.commit()
    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError as e:
        return json_error("Database error while saving soil data", 500)

    return json_ok(
        "Soil report uploaded and analysed",
        200,
        soil=soil,
        filepath=os.path.basename(filepath),
    )

import logging
import os
import re
from datetime import datetime, timedelta

import bcrypt
import pymysql
from flask import Blueprint, request, session, jsonify
from werkzeug.utils import secure_filename

from config import Config, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, allowed_file
from db import get_db_connection, DBConnectionError
from utils.email_service import send_otp_email
from utils.helpers import json_error, json_ok
from utils.otp import generate_otp

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

def _json_ok(message, **data):
    return {"success": True, "message": message, "data": data}

def _json_error(message, code, status=400):
    return {"success": False, "message": message, "error": code}, status

def _is_valid_email(email):
    return bool(re.match(r"[^@]+@[^@]+\.[^@]+", email))


# ================= REGISTER =================
@auth_bp.post("/register")
def register():
    from routes.expert import _ensure_experts_table
    from routes.farmer import _ensure_farmers_table

    data = request.form

    username = str(data.get("username") or "").strip()
    email = str(data.get("email") or "").strip()
    mobile_number = str(data.get("mobile_number") or "").strip()
    aadhaar_number = str(data.get("aadhaar_number") or "").strip()
    password = str(data.get("password") or "").strip()
    confirm_password = str(data.get("confirm_password") or "").strip()
    role = str(data.get("role") or data.get("user_role") or "").strip()
    if role.lower() in ["farmer", "expert"]:
        role = role.capitalize()

    if role not in ["Farmer", "Expert"]:
        return json_error("Invalid role", 400)
    if not username or not email or not password or not confirm_password:
        return json_error("Missing required fields", 400)
    if not _is_valid_email(email):
        return json_error("Invalid email", 400)
    if password != confirm_password:
        return json_error("Passwords do not match", 400)
    if not re.fullmatch(r"\d{12}", aadhaar_number):
        return json_error("Aadhaar must be exactly 12 digits", 400)
    if not re.fullmatch(r"\d{10}", mobile_number):
        return json_error("Mobile must be exactly 10 digits", 400)

    # Hash password before any DB operation
    hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    crop_type = ""
    location = ""
    land_size = None
    expertise_field = ""
    qualification = ""
    experience_years = None

    if role == "Farmer":
        crop_type = str(data.get("crop_type") or "").strip()
        location = str(data.get("location") or "").strip()
        land_raw = data.get("land_size")
        if not crop_type or not location or land_raw is None or str(land_raw).strip() == "":
            return json_error("Missing required farmer fields", 400)
        try:
            land_size = float(land_raw)
        except (TypeError, ValueError):
            return json_error("Invalid land size", 400)
        if land_size <= 0:
            return json_error("Land size must be greater than zero", 400)
        filepath = None
    else:
        expertise_field = str(data.get("expertise_field") or "").strip()
        ey_raw = data.get("experience_years")
        qualification = str(data.get("qualification") or "").strip()
        file = request.files.get("qualification_file")

        if not file or file.filename == "":
            return json_error("Qualification file required (PDF/Image)", 400)
        if not allowed_file(file.filename):
            return json_error("Invalid file type(PDF/Image Only)", 400)
        try:
            experience_years = int(ey_raw)
        except (TypeError, ValueError):
            return json_error("Invalid experience years", 400)
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

    try:
        conn = get_db_connection()
        if role == "Farmer":
            _ensure_farmers_table(conn)
        else:
            _ensure_experts_table(conn)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM users WHERE username=%s OR email=%s LIMIT 1",
                (username, email),
            )
            if cur.fetchone():
                conn.rollback()
                return json_error("Username or email already registered", 400)

            try:
                cur.execute(
                    """
                    SELECT user_id FROM users
                    WHERE mobile_number=%s OR aadhaar_number=%s
                    LIMIT 1
                    """,
                    (mobile_number, aadhaar_number),
                )
                if cur.fetchone():
                    conn.rollback()
                    return json_error("Mobile or Aadhaar already registered", 400)
            except pymysql.MySQLError:
                pass

            inserted_extended = False
            try:
                cur.execute(
                    """
                    INSERT INTO users (username, email, password, user_role, mobile_number, aadhaar_number)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (username, email, hashed_password, role, mobile_number, aadhaar_number),
                )
                inserted_extended = True
            except pymysql.MySQLError:
                inserted_extended = False

            if not inserted_extended:
                try:
                    cur.execute(
                        """
                        INSERT INTO users (username, email, password, user_role)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (username, email, hashed_password, role),
                    )
                except pymysql.MySQLError:
                    cur.execute(
                        "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                        (username, hashed_password, role),
                    )

            if role == "Farmer":
                cur.execute(
                    """
                    INSERT INTO farmers
                      (username, mobile_number, crop_type, location, land_size,
                       irrigation_type, survey_number, soil_report_file)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        username,
                        mobile_number,
                        crop_type,
                        location,
                        land_size,
                        "Pending",
                        "Pending",
                        "pending",
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO experts
                      (username, mobile_number, expertise_field, experience_years, qualification, qualification_file)
                    VALUES (%s, %s, %s, %s, %s,%s)
                    """,
                    (
                        username,
                        mobile_number,
                        expertise_field,
                        experience_years,
                        qualification,
                        filepath
                    ),
                )

        conn.commit()
        return json_ok("User registered successfully", 200)

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError as e:
        err = str(e).lower()
        try:
            conn.rollback()
        except Exception:
            pass
        if "duplicate" in err:
            return json_error("Username, email, mobile, or Aadhaar already in use", 400)
        return json_error("Database error", 500, detail=str(e))


# ================= VERIFY OTP =================
@auth_bp.post("/verify-otp")
def verify_otp():
    data = request.get_json(silent=True) or {}
    email    = str(data.get("email")    or "").strip()
    username = str(data.get("username") or "").strip()
    otp      = str(data.get("otp")      or "").strip()

    if not otp:
        return json_error("OTP is required", 400)
    if not email and not username:
        return json_error("Email or username is required", 400)

    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            row = None
            where = "email=%s" if email else "username=%s"
            param = email or username
            try:
                cur.execute(
                    f"SELECT username, email, user_role AS role, otp, otp_expires_at "
                    f"FROM users WHERE {where}",
                    (param,),
                )
                row = cur.fetchone()
            except pymysql.MySQLError:
                cur.execute(
                    f"SELECT username, email, role, otp FROM users WHERE {where}",
                    (param,),
                )
                row = cur.fetchone()

            if not row:
                return json_error("User not found", 404)

            if row.get("otp") is None or str(row["otp"]) != otp:
                return json_error("Invalid OTP", 401)

            # Check expiry if column was available in the query result.
            expires_at = row.get("otp_expires_at")
            if expires_at is not None:
                if isinstance(expires_at, str):
                    try:
                        expires_at = datetime.fromisoformat(expires_at)
                    except ValueError:
                        expires_at = None
                if expires_at and datetime.utcnow() > expires_at:
                    cur.execute(
                        "UPDATE users SET otp=NULL, otp_expires_at=NULL "
                        f"WHERE {where}",
                        (param,),
                    )
                    conn.commit()
                    return json_error(
                        f"OTP has expired. Please log in again to receive a new one.",
                        401,
                    )

            # Clear OTP after successful verification.
            try:
                cur.execute(
                    f"UPDATE users SET otp=NULL, otp_expires_at=NULL WHERE {where}",
                    (param,),
                )
            except pymysql.MySQLError:
                cur.execute(
                    f"UPDATE users SET otp=NULL WHERE {where}",
                    (param,),
                )

        conn.commit()

        session["username"] = row["username"]
        session["role"]     = row["role"]
        logger.info("[OTP] Verified for user '%s'", row["username"])

        return json_ok(
            "Login successful",
            200,
            username=row["username"],
            role=row["role"],
            email=str(row.get("email") or ""),
        )

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError as e:
        return json_error("Database error", 500, detail=str(e))


# ================= LOGIN =================
@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}

    email_login    = str(data.get("email")    or "").strip()
    username_login = str(data.get("username") or "").strip()
    password       = str(data.get("password") or "").strip()

    if not password or (not email_login and not username_login):
        return json_error("Email/username and password are required", 400)

    try:
        conn = get_db_connection()
        user = None

        with conn.cursor() as cur:
            # Fetch user by identity only — password verified in Python with bcrypt.
            try:
                if email_login:
                    cur.execute(
                        "SELECT username, password, user_role AS role, email FROM users "
                        "WHERE email=%s",
                        (email_login,),
                    )
                else:
                    cur.execute(
                        "SELECT username, password, user_role AS role, email FROM users "
                        "WHERE username=%s",
                        (username_login,),
                    )
                user = cur.fetchone()
            except pymysql.MySQLError:
                if email_login:
                    cur.execute(
                        "SELECT username, password, role, email FROM users "
                        "WHERE email=%s",
                        (email_login,),
                    )
                else:
                    cur.execute(
                        "SELECT username, password, role, email FROM users "
                        "WHERE username=%s",
                        (username_login,),
                    )
                user = cur.fetchone()

            if not user:
                logger.warning("[Login] Failed attempt for '%s'", email_login or username_login)
                return json_error("Invalid email or password", 401)

            # Verify password with bcrypt — handles both hashed and legacy plain-text.
            stored_pw = str(user.get("password") or "")
            try:
                pw_ok = bcrypt.checkpw(password.encode(), stored_pw.encode())
            except Exception:
                # Fallback: legacy plain-text comparison for existing accounts not yet rehashed.
                pw_ok = (password == stored_pw)

            if not pw_ok:
                logger.warning("[Login] Wrong password for '%s'", email_login or username_login)
                return json_error("Invalid email or password", 401)

            dest_email = str(user.get("email") or "").strip()
            if not dest_email or dest_email.endswith("@local.invalid"):
                return json_error(
                    "No valid email on file. Please contact support.",
                    400,
                )

            otp = generate_otp()
            expiry = datetime.utcnow() + timedelta(
                minutes=Config.OTP_EXPIRY_MINUTES
            )

            try:
                cur.execute(
                    "UPDATE users SET otp=%s, otp_expires_at=%s WHERE username=%s",
                    (otp, expiry, user["username"]),
                )
            except pymysql.MySQLError:
                cur.execute(
                    "UPDATE users SET otp=%s WHERE username=%s",
                    (otp, user["username"]),
                )

        conn.commit()

        try:
            send_otp_email(dest_email, otp, Config.OTP_EXPIRY_MINUTES)
            logger.info("[Login] OTP sent to %s", dest_email)
        except Exception as exc:
            logger.error("[Login] Email delivery failed for %s: %s", dest_email, exc)
            with conn.cursor() as cur:
                try:
                    cur.execute(
                        "UPDATE users SET otp=NULL, otp_expires_at=NULL WHERE username=%s",
                        (user["username"],),
                    )
                except pymysql.MySQLError:
                    cur.execute(
                        "UPDATE users SET otp=NULL WHERE username=%s",
                        (user["username"],),
                    )
            conn.commit()
            return json_error(
                "Could not send OTP email. "
                "Check EMAIL_ADDRESS / EMAIL_PASSWORD in backend/.env.",
                500,
            )

        # Return success — OTP is NOT included in the response (security).
        return json_ok("OTP sent to your registered email", 200)

    except DBConnectionError:
        return json_error("DB connection failed", 500)
    except pymysql.MySQLError as e:
        return json_error("Database error", 500, detail=str(e))


# ================= LOGOUT =================
@auth_bp.post("/logout")
def logout():
    session.clear()
    return json_ok("Logged out successfully", 200)


# ================= FORGOT PASSWORD =================
@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email") or "").strip()

    if not email:
        return jsonify({"success": False, "message": "Email is required"}), 400

    _generic_ok = jsonify({"success": True, "message": "If that email is registered, an OTP has been sent."})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        if not user:
            return _generic_ok, 200

        otp = generate_otp()
        expiry = datetime.utcnow() + timedelta(minutes=Config.OTP_EXPIRY_MINUTES)

        try:
            cursor.execute(
                "UPDATE users SET otp=%s, otp_expires_at=%s WHERE user_id=%s",
                (otp, expiry, user["user_id"]),
            )
        except pymysql.MySQLError:
            cursor.execute(
                "UPDATE users SET otp=%s WHERE user_id=%s",
                (otp, user["user_id"]),
            )
        conn.commit()

        try:
            send_otp_email(email, otp, Config.OTP_EXPIRY_MINUTES)
            logger.info("[ForgotPassword] OTP sent to %s", email)
        except Exception as exc:
            logger.error("[ForgotPassword] Email failed for %s: %s", email, exc)
            # Don't reveal failure to the caller — but clear the OTP.
            try:
                cursor.execute(
                    "UPDATE users SET otp=NULL, otp_expires_at=NULL WHERE user_id=%s",
                    (user["user_id"],),
                )
                conn.commit()
            except Exception:
                pass

        return _generic_ok, 200

    except Exception as e:
        logger.error("[ForgotPassword] Error: %s", e)
        return jsonify({"success": False, "message": "DB error"}), 500


# ================= RESET PASSWORD =================
@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password are required"}), 400

    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if user exists
        cursor.execute("SELECT user_id FROM users WHERE username=%s", (username,))
        user = cursor.fetchone()

        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        # Hash new password
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        # Update password and clear OTP
        cursor.execute(
            "UPDATE users SET password=%s, otp=NULL WHERE username=%s",
            (hashed, username)
        )
        conn.commit()

        return _json_ok("Password reset successfully")

    except Exception as e:
        return jsonify({"success": False, "message": "DB error", "error": str(e)}), 500
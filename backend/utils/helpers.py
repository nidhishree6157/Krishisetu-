import re
from functools import wraps

from flask import jsonify, session


def json_error(message, status_code=400, **extra):
    payload = {"success": False, "message": message}
    if extra:
        payload["errors"] = extra
    return jsonify(payload), status_code


def json_ok(message="OK", status_code=200, **data):
    payload = {"success": True, "message": message}
    if data:
        payload["data"] = data
    return jsonify(payload), status_code


def require_fields(data: dict, required: list[str]):
    missing = [k for k in required if not data.get(k)]
    return missing


def is_valid_mobile(mobile: str) -> bool:
    # Accept 10-15 digits; supports country codes without '+'
    return bool(re.fullmatch(r"\d{10,15}", str(mobile or "").strip()))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return json_error("Authentication required", 401)
        return fn(*args, **kwargs)

    return wrapper


def role_required(required_role: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("username"):
                return json_error("Authentication required", 401)
            if session.get("role") != required_role:
                return json_error("Forbidden: insufficient role", 403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


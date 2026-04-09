"""
farm_context_service.py
───────────────────────
Shared resolution of farmer_id, profile row, and soil_data for smart modules.
Always reads the latest rows from the DB on each request (no caching).
"""

from __future__ import annotations

from flask import session

FALLBACK_FARMER_ID = 1

SOIL_MESSAGE = "Please complete soil analysis first"


def resolve_farmer_id(conn) -> int:
    try:
        username = session.get("username")
        if username:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1",
                    (username,),
                )
                row = cur.fetchone()
                if row and row.get("farmer_id"):
                    return int(row["farmer_id"])
    except Exception:
        pass
    return FALLBACK_FARMER_ID


def fetch_farmer_row(conn, farmer_id: int) -> dict | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT farmer_id, username, mobile_number, crop_type, location, land_size
                FROM farmers
                WHERE farmer_id = %s
                LIMIT 1
                """,
                (farmer_id,),
            )
            return cur.fetchone() or None
    except Exception:
        return None


def fetch_soil_row(conn, farmer_id: int) -> dict | None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT nitrogen, phosphorus, potassium, soil_ph, ph, organic_carbon
                FROM soil_data
                WHERE farmer_id = %s
                LIMIT 1
                """,
                (farmer_id,),
            )
            return cur.fetchone() or None
    except Exception:
        return None


def _float_or_none(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def soil_row_usable(row: dict | None) -> bool:
    """True when soil_data row has meaningful lab values (for gating recommendations)."""
    if not row:
        return False
    for key in ("nitrogen", "phosphorus", "potassium"):
        fv = _float_or_none(row.get(key))
        if fv is not None and fv > 0:
            return True
    ph = _float_or_none(row.get("ph"))
    if ph is None:
        ph = _float_or_none(row.get("soil_ph"))
    if ph is not None and 3.0 <= ph <= 10.0:
        return True
    return False


def payload_has_soil_values(payload: dict) -> bool:
    """True when request payload (after DB merge) has usable NPK / pH for ML or fertilizer."""
    for key in ("nitrogen", "phosphorus", "potassium"):
        fv = _float_or_none(payload.get(key))
        if fv is not None and fv > 0:
            return True
    ph = _float_or_none(payload.get("ph"))
    if ph is None:
        ph = _float_or_none(payload.get("soil_ph"))
    if ph is not None and 3.0 <= ph <= 10.0:
        return True
    return False


def merge_farmer_profile_into_payload(payload: dict, farmer_row: dict | None) -> None:
    """Fill location / crop from saved profile when the client omits them."""
    if not farmer_row:
        return
    loc = str(payload.get("location") or "").strip()
    if not loc:
        fl = str(farmer_row.get("location") or "").strip()
        if fl:
            payload["location"] = fl
    crop = payload.get("crop")
    if crop is None or (isinstance(crop, str) and not str(crop).strip()):
        fc = str(farmer_row.get("crop_type") or "").strip()
        if fc:
            payload["crop"] = fc


def merge_soil_into_payload(payload: dict, soil_row: dict | None) -> None:
    """Fill NPK / pH from latest soil_data when keys are absent (None / missing)."""
    if not soil_row:
        return
    for fld, col in (
        ("nitrogen", "nitrogen"),
        ("phosphorus", "phosphorus"),
        ("potassium", "potassium"),
    ):
        if payload.get(fld) is not None:
            continue
        val = soil_row.get(col)
        if val is not None:
            try:
                payload[fld] = float(val)
            except (TypeError, ValueError):
                pass
    if payload.get("ph") is not None or payload.get("soil_ph") is not None:
        return
    sp = soil_row.get("ph")
    if sp is None:
        sp = soil_row.get("soil_ph")
    if sp is not None:
        try:
            payload["ph"] = float(sp)
        except (TypeError, ValueError):
            pass

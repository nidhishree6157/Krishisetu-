"""
notification.py
───────────────
Notification feed — aggregates alerts from:
  • disease_alerts  (type = "disease")
  • expert_queries  (status = "Answered", type = "expert")

Endpoints
─────────
  GET  /notifications          → list + unread count
  POST /notifications/read     → mark one or many as read
"""

from __future__ import annotations

import hashlib

from flask import Blueprint, jsonify, request, session

from db import DBConnectionError, get_db_connection
from utils.helpers import json_error

notif_bp = Blueprint("notifications", __name__)


# ── helpers ────────────────────────────────────────────────────────────────────

def _stable_ref(prefix: str, row_id, *fallback_parts) -> str:
    """
    Return a stable notification reference string.
    Prefer `row_id` when present; otherwise hash fallback_parts.
    """
    if row_id:
        return f"{prefix}_{row_id}"
    digest = hashlib.md5(
        ":".join(str(p) for p in fallback_parts).encode()
    ).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _get_farmer_id(conn, username: str):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT farmer_id FROM farmers WHERE username=%s LIMIT 1",
                (username,),
            )
            row = cur.fetchone()
        return (row or {}).get("farmer_id")
    except Exception:
        return None


def _get_read_refs(conn, username: str) -> set[str]:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT notification_ref FROM notifications_read WHERE session_user=%s",
                (username,),
            )
            rows = cur.fetchall()
        return {r["notification_ref"] for r in rows}
    except Exception:
        return set()


def _fmt_time(ts) -> str:
    """Best-effort ISO string from whatever the DB returns."""
    if ts is None:
        return ""
    try:
        return ts.isoformat(sep=" ", timespec="seconds")
    except Exception:
        return str(ts)


def _relative_label(ts_str: str) -> str:
    """Human-friendly relative time label (e.g. '2 hours ago')."""
    if not ts_str:
        return ""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:
            return "Just now"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return ts_str[:16] if len(ts_str) >= 16 else ts_str


# ── GET /notifications ─────────────────────────────────────────────────────────

@notif_bp.get("/")
def get_notifications():
    """
    Returns latest 20 notifications, newest first.
    Each item: {id, type, icon, message, time, time_label, read}
    """
    username  = session.get("username", "")
    conn      = get_db_connection()
    farmer_id = 1
    read_refs = _get_read_refs(conn, username)

    notifications: list[dict] = []

    # ── Source 1: disease_alerts ───────────────────────────────────────────────
    if farmer_id:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM   disease_alerts
                    WHERE  farmer_id = %s
                    ORDER  BY alert_date DESC
                    LIMIT  15
                    """,
                    (farmer_id,),
                )
                alerts = cur.fetchall()
            for a in alerts:
                row_id = a.get("alert_id") or a.get("id") or a.get("disease_alert_id")
                ref    = _stable_ref(
                    "disease", row_id,
                    farmer_id, a.get("disease_name", ""), a.get("alert_date", "")
                )
                ts = _fmt_time(a.get("alert_date"))
                notifications.append({
                    "id":         ref,
                    "type":       "disease",
                    "icon":       "virus",
                    "message":    f"{a.get('disease_name', 'Disease')} detected in your crop",
                    "time":       ts,
                    "time_label": _relative_label(ts),
                    "read":       ref in read_refs,
                })
        except Exception as exc:
            print(f"[Notifications] disease_alerts error: {exc}")

    # ── Source 2: expert_queries (Answered) ────────────────────────────────────
    if farmer_id:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT query_id, query_text, expert_response,
                           response_date, query_date
                    FROM   expert_queries
                    WHERE  farmer_id = %s
                      AND  LOWER(status) IN ('answered', 'replied')
                    ORDER  BY COALESCE(response_date, query_date) DESC
                    LIMIT  15
                    """,
                    (farmer_id,),
                )
                queries = cur.fetchall()
            for q in queries:
                qid = q.get("query_id") or q.get("id")
                if not qid:
                    continue
                ref  = f"expert_{qid}"
                resp = (q.get("expert_response") or "").strip()
                msg  = (
                    f"Expert replied: {resp[:55]}…" if len(resp) > 55
                    else f"Expert replied: {resp}" if resp
                    else "Expert replied to your query"
                )
                ts = _fmt_time(q.get("response_date") or q.get("query_date"))
                notifications.append({
                    "id":         ref,
                    "type":       "expert",
                    "icon":       "user-tie",
                    "message":    msg,
                    "time":       ts,
                    "time_label": _relative_label(ts),
                    "read":       ref in read_refs,
                })
        except Exception as exc:
            print(f"[Notifications] expert_queries error: {exc}")

    # Sort newest first
    notifications.sort(key=lambda x: x["time"] or "", reverse=True)

    unread_count = sum(1 for n in notifications if not n["read"])

    return jsonify({
        "success":      True,
        "notifications": notifications[:20],
        "unread_count": unread_count,
    }), 200


# ── POST /notifications/read ───────────────────────────────────────────────────

@notif_bp.post("/read")
def mark_read():
    """
    Mark one or many notifications as read.
    Body: {"id": "disease_3"}  OR  {"ids": ["disease_3", "expert_7"]}
    """
    data     = request.get_json(silent=True) or {}
    username = session.get("username") or "guest"

    ref_single = data.get("id")
    refs: list[str] = data.get("ids") or ([ref_single] if ref_single else [])

    if not refs:
        return json_error("Provide 'id' or 'ids'", 400)

    conn   = get_db_connection()
    marked = 0
    for ref in refs:
        if not ref:
            continue
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT IGNORE INTO notifications_read (session_user, notification_ref)
                    VALUES (%s, %s)
                    """,
                    (username, str(ref)),
                )
            marked += 1
        except Exception as exc:
            print(f"[Notifications] mark_read error for {ref!r}: {exc}")

    # Commit once after all inserts — was missing, causing read-state to never persist
    try:
        conn.commit()
    except Exception as exc:
        print(f"[Notifications] commit failed: {exc}")

    return jsonify({"success": True, "marked": marked}), 200

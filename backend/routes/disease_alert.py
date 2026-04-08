from flask import Blueprint, session
from db import get_db_connection

disease_alert_bp = Blueprint("disease_alert", __name__)


@disease_alert_bp.route("/alerts", methods=["GET"])
def get_alerts():
    if "username" not in session:
        return {"success": False, "message": "Unauthorized"}, 401

    username = session["username"]

    conn = get_db_connection()
    with conn.cursor() as cur:
        # get farmer_id
        cur.execute("SELECT farmer_id FROM farmers WHERE username=%s", (username,))
        farmer = cur.fetchone()

        if not farmer:
            return {"success": False, "message": "Farmer profile not found"}, 400

        farmer_id = farmer["farmer_id"]

        # get alerts
        cur.execute("""
            SELECT disease_name, alert_date 
            FROM disease_alerts 
            WHERE farmer_id=%s 
            ORDER BY alert_date DESC
        """, (farmer_id,))

        alerts = cur.fetchall()

    return {"success": True, "data": alerts}
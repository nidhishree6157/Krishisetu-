from flask import Blueprint, jsonify, request, session
from db import get_db_connection

crop_bp = Blueprint('crop', __name__)


def _get_farmer_id_from_session(cursor):
    username = session.get('username')
    if not username:
        return None, (jsonify({"success": False, "message": "Not logged in"}), 401)

    cursor.execute("SELECT farmer_id FROM farmers WHERE username=%s", (username,))
    farmer = cursor.fetchone()
    if not farmer:
        return None, (
            jsonify({"success": False, "message": "Please create farmer profile first"}),
            400,
        )

    return farmer.get("farmer_id"), None


# ===============================
# ADD CROP
# ===============================
@crop_bp.route('/add', methods=['POST'])
def add_crop():
    if 'username' not in session:
        return jsonify({"success": False, "message": "Not logged in"}), 401

    data = request.get_json() or {}

    crop_name = data.get('crop_name')
    planting_date = data.get('planting_date')
    expected_harvest = data.get('expected_harvest')

    if not crop_name:
        return jsonify({"success": False, "message": "Crop name required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        farmer_id, err = _get_farmer_id_from_session(cursor)
        if err:
            return err

        cursor.execute("""
            INSERT INTO crops (farmer_id, crop_name, planting_date, expected_harvest)
            VALUES (%s, %s, %s, %s)
        """, (farmer_id, crop_name, planting_date, expected_harvest))

        conn.commit()

        return jsonify({"success": True, "message": "Crop added"}), 201

    except Exception as e:
        return jsonify({"success": False, "message": "DB error", "error": str(e)}), 500


# ===============================
# GET CROPS
# ===============================
@crop_bp.route('/list', methods=['GET'])
def get_crops():
    if 'username' not in session:
        return jsonify({"success": False, "message": "Not logged in"}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        farmer_id, err = _get_farmer_id_from_session(cursor)
        if err:
            return err

        cursor.execute("SELECT * FROM crops WHERE farmer_id=%s", (farmer_id,))
        crops = cursor.fetchall()

        return jsonify({"success": True, "data": crops}), 200

    except Exception as e:
        return jsonify({"success": False, "message": "DB error", "error": str(e)}), 500
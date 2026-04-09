import os

from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from dotenv import load_dotenv
from groq import Groq

# Load backend/.env before any other local imports so all env vars are available.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from config import Config
from db import DBConnectionError, get_db_connection
from routes import register_blueprints
from routes.auth import auth_bp


_groq_api_key = os.getenv("GROQ_API_KEY")
client = Groq(api_key=_groq_api_key) if _groq_api_key else None


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.secret_key = "super-secret-key"
    CORS(app, supports_credentials=True)

    # Register blueprints — all registrations live in routes/__init__.py
    register_blueprints(app)
    if "auth" not in app.blueprints:
        app.register_blueprint(auth_bp, url_prefix="/auth")

    # =========================
    # CHATBOT API — Smart Agriculture AI Assistant
    # =========================

    def _chatbot_insight(crop, disease, pest, yield_val, market_price):
        """Generate a one-line proactive insight from available context."""
        if disease and disease.lower() not in ("healthy", "none", ""):
            return f"Treat {disease} immediately to prevent yield loss."
        if pest and pest.lower() not in ("healthy", "none", ""):
            return f"Control {pest} early — can save 20-40% of yield."
        if yield_val and market_price:
            try:
                y = float(str(yield_val).replace(",", "").split()[0])
                p = float(str(market_price).replace(",", "").replace("\u20b9", "").split()[0])
                revenue = int((y / 100) * p)
                return f"Est. revenue \u20b9{revenue:,} from {y:.0f} kg at \u20b9{p:.0f}/quintal."
            except Exception:
                pass
        if crop:
            return f"Optimise inputs for {crop} to maximise this season's returns."
        return "Share your crop, disease or yield data for smarter advice."

    @app.route("/api/chatbot", methods=["POST"])
    def chatbot():
        data = request.json or {}
        user_message = str(data.get("message") or "").strip()
        if not user_message:
            return jsonify({"reply": "Please type a message.", "confidence": "low"}), 400

        # ── Pull farm context ────────────────────────────────────────────────
        ctx          = data.get("context") or {}
        crop         = str(ctx.get("crop")         or data.get("crop")         or "").strip()
        disease      = str(ctx.get("disease")       or data.get("disease")      or "").strip()
        pest         = str(ctx.get("pest")          or data.get("pest")         or "").strip()
        yield_val    = str(ctx.get("yield_value")   or data.get("yield_value")  or "").strip()
        market_price = str(ctx.get("market_price")  or data.get("market_price") or "").strip()
        cost         = str(ctx.get("cost")          or data.get("cost")         or "").strip()
        location     = str(ctx.get("location")      or data.get("location")     or "").strip()

        # ── Build context block ──────────────────────────────────────────────
        ctx_lines = []
        if crop:         ctx_lines.append(f"Crop: {crop}")
        if location:     ctx_lines.append(f"Location: {location}")
        if disease:      ctx_lines.append(f"Disease detected: {disease}")
        if pest:         ctx_lines.append(f"Pest detected: {pest}")
        if yield_val:    ctx_lines.append(f"Predicted yield: {yield_val} kg")
        if market_price: ctx_lines.append(f"Market price: \u20b9{market_price}/quintal")
        if cost:         ctx_lines.append(f"Farming cost: \u20b9{cost}")
        context_block = "\n".join(ctx_lines)

        # ── Decision mode detection ──────────────────────────────────────────
        msg_lower = user_message.lower()
        decision_kw = [
            "profit", "best crop", "what should i do", "should i",
            "which crop", "maximize", "earn more", "loss", "income",
            "sell", "harvest now", "advice", "recommend",
        ]
        is_decision = any(kw in msg_lower for kw in decision_kw)

        # ── System prompt ────────────────────────────────────────────────────
        system_prompt = (
            "You are KrishiSetu — an expert agriculture advisor for Indian farmers. "
            "When farm context is provided (crop, disease, pest, yield, price, cost), "
            "use it to give SPECIFIC, PRACTICAL advice for that exact situation. "
            "For profit or 'what should I do' questions, combine yield + price + cost "
            "to give a concrete financial recommendation with numbers. "
            "Keep answers to 3-5 bullet points. Be direct, not generic. "
            "Focus on: increasing yield, reducing disease/pest loss, maximising profit."
        )

        # ── Compose user message ─────────────────────────────────────────────
        if context_block:
            full_msg = f"Farm Context:\n{context_block}\n\nQuestion: {user_message}"
            if is_decision:
                full_msg += (
                    "\n\n(Give a specific financial/yield decision based on the "
                    "context above, including numbers where possible.)"
                )
        else:
            full_msg = user_message

        try:
            if client is None:
                raise RuntimeError("GROQ_API_KEY not set")

            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": full_msg},
                ],
                max_tokens=450,
                temperature=0.35,
            )

            reply_raw = response.choices[0].message.content.strip()
            reply     = reply_raw.replace("\n", "<br>")

            # ── Confidence ───────────────────────────────────────────────────
            confidence = "high"
            if any(w in msg_lower for w in ("asdf", "qwerty", "random", "test123")):
                confidence = "low"
            if any(p in reply_raw.lower() for p in ("not sure", "provide more details", "i don't know")):
                confidence = "low"
            if is_decision and not context_block:
                confidence = "medium"

            # ── Insight ──────────────────────────────────────────────────────
            insight = _chatbot_insight(crop, disease, pest, yield_val, market_price)

            # ── Auto escalation (unchanged) ──────────────────────────────────
            escalated = False
            if confidence == "low":
                try:
                    conn = get_db_connection()
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO expert_queries (farmer_id, query_text, status) "
                            "VALUES (%s, %s, 'pending')",
                            (1, user_message),
                        )
                        conn.commit()
                    escalated = True
                except Exception:
                    pass

            return jsonify({
                "reply":      reply,
                "confidence": confidence,
                "escalated":  escalated,
                "insight":    insight,
            })

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================
    # GET EXPERT QUERIES
    # =========================
    @app.route("/api/expert/queries", methods=["GET"])
    def get_queries():
        try:
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM expert_queries ORDER BY query_date DESC")
                data = cur.fetchall()

            return jsonify({"success": True, "data": data})

        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    # =========================
    # EXPERT RESPONSE
    # =========================
    @app.route("/api/expert/respond", methods=["POST"])
    def expert_respond():
        try:
            data = request.json or {}
            query_id = data.get("query_id")
            reply = data.get("reply")

            if not query_id or not reply:
                return jsonify({"success": False, "message": "Missing data"}), 400

            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE expert_queries
                    SET expert_response = %s,
                        response_date   = NOW(),
                        status          = 'Answered'
                    WHERE query_id = %s
                    """,
                    (reply, query_id),
                )
            conn.commit()

            return jsonify({
                "success": True,
                "message": "Reply saved successfully"
            })

        except Exception as e:
            return jsonify({
                "success": False,
                "message": str(e)
            }), 500

    # =========================
    # PROFILE API — no strict auth, farmer_id=1 fallback
    # =========================

    _FALLBACK_FARMER_ID = 1

    def _profile_get_username_and_farmer(conn):
        """
        Return (username, farmer_row, user_row) using the session user when
        available, falling back to farmer_id = _FALLBACK_FARMER_ID.
        """
        username = session.get("username")
        farmer_row = None
        user_row   = {}

        if username:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username, email, aadhaar_number "
                    "FROM users WHERE username=%s LIMIT 1",
                    (username,),
                )
                user_row = cur.fetchone() or {}
                cur.execute(
                    "SELECT username, mobile_number, crop_type, location, land_size, "
                    "       irrigation_type, survey_number, soil_report_file, "
                    "       farmer_id "
                    "FROM farmers WHERE username=%s LIMIT 1",
                    (username,),
                )
                farmer_row = cur.fetchone()

        # Fallback: look up farmer_id=1
        if not farmer_row:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username, mobile_number, crop_type, location, land_size, "
                    "       irrigation_type, survey_number, soil_report_file, "
                    "       farmer_id "
                    "FROM farmers WHERE farmer_id=%s LIMIT 1",
                    (_FALLBACK_FARMER_ID,),
                )
                farmer_row = cur.fetchone()
                if farmer_row:
                    fb_username = farmer_row.get("username", "")
                    if fb_username:
                        cur.execute(
                            "SELECT username, email, aadhaar_number "
                            "FROM users WHERE username=%s LIMIT 1",
                            (fb_username,),
                        )
                        user_row = cur.fetchone() or {}

        return username, farmer_row, user_row

    @app.route("/api/profile", methods=["GET"])
    def api_get_profile():
        """
        GET /api/profile
        ─────────────────
        Returns the farmer's profile as a flat JSON object.
        Uses session user when logged in; falls back to farmer_id=1.
        """
        try:
            conn = get_db_connection()
            username, farmer_row, user_row = _profile_get_username_and_farmer(conn)

            # Read soil data from soil_data table (single source of truth)
            soil = {}
            fid  = (farmer_row or {}).get("farmer_id")
            if fid:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT nitrogen, phosphorus, potassium, ph, soil_ph, created_at "
                        "FROM soil_data WHERE farmer_id=%s LIMIT 1",
                        (fid,),
                    )
                    srow = cur.fetchone()
                    if srow:
                        ph_val = srow.get("ph") or srow.get("soil_ph")
                        soil = {
                            "nitrogen":   srow.get("nitrogen"),
                            "phosphorus": srow.get("phosphorus"),
                            "potassium":  srow.get("potassium"),
                            "ph":         float(ph_val) if ph_val is not None else None,
                        }

            fr = farmer_row or {}
            ur = user_row   or {}

            return jsonify({
                "success":      True,
                "username":     ur.get("username")     or fr.get("username", ""),
                "email":        ur.get("email", ""),
                "aadhaar":      ur.get("aadhaar_number", ""),
                "mobile":       fr.get("mobile_number", ""),
                "location":     fr.get("location", ""),
                "land_size":    fr.get("land_size"),
                "crop_type":    fr.get("crop_type", ""),
                "irrigation":   fr.get("irrigation_type", ""),
                "survey_number": fr.get("survey_number", ""),
                "has_soil_data": bool(soil),
                **soil,
            })
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

    @app.route("/profile", methods=["GET"])
    def get_profile():
        """GET /profile — same payload as GET /api/profile; always JSON."""
        return api_get_profile()

    @app.route("/api/profile/save", methods=["POST"])
    def api_save_profile():
        """
        POST /api/profile/save
        ──────────────────────
        Body: { mobile, crop_type, location, land_size, irrigation, survey_number }
        Inserts or updates the farmers row.
        Returns the saved profile on success.
        """
        try:
            data = request.get_json(silent=True) or {}

            mobile      = str(data.get("mobile")      or data.get("mobile_number", "")).strip()
            crop_type   = str(data.get("crop_type",   "")).strip()
            location    = str(data.get("location",    "")).strip()
            irrigation  = str(data.get("irrigation")  or data.get("irrigation_type", "")).strip()
            survey_num  = str(data.get("survey_number", "")).strip()

            try:
                land_size = float(data.get("land_size") or 0)
            except (TypeError, ValueError):
                land_size = 0.0

            # Validate required fields
            missing = [f for f, v in [
                ("mobile",    mobile),
                ("crop_type", crop_type),
                ("location",  location),
            ] if not v]
            if missing:
                return jsonify({"success": False,
                                "message": f"Required: {', '.join(missing)}"}), 400

            # Validate mobile
            import re as _re
            if not _re.fullmatch(r"\d{10,15}", mobile):
                return jsonify({"success": False,
                                "message": "Mobile must be 10–15 digits."}), 400

            conn     = get_db_connection()
            username = session.get("username")

            # Identify the target username — session or farmer_id=1 fallback
            if not username:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT username FROM farmers WHERE farmer_id=%s LIMIT 1",
                        (_FALLBACK_FARMER_ID,),
                    )
                    row = cur.fetchone()
                    username = row.get("username") if row else None

            if not username:
                return jsonify({"success": False,
                                "message": "No user identified. Please log in."}), 400

            # Ensure farmers table and extra columns exist
            from routes.farmer import _ensure_farmers_table, _ensure_soil_columns
            _ensure_farmers_table(conn)
            _ensure_soil_columns(conn)

            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM farmers WHERE username=%s LIMIT 1", (username,))
                exists = cur.fetchone() is not None

                if exists:
                    cur.execute(
                        """
                        UPDATE farmers
                        SET mobile_number=%s, crop_type=%s, location=%s,
                            land_size=%s, irrigation_type=%s, survey_number=%s
                        WHERE username=%s
                        """,
                        (mobile, crop_type, location, land_size,
                         irrigation, survey_num, username),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO farmers
                          (username, mobile_number, crop_type, location,
                           land_size, irrigation_type, survey_number, soil_report_file)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, '')
                        """,
                        (username, mobile, crop_type, location,
                         land_size, irrigation, survey_num),
                    )
            conn.commit()

            # Return fresh profile so the frontend can reload immediately
            _, farmer_row, user_row = _profile_get_username_and_farmer(conn)
            fr = farmer_row or {}
            ur = user_row   or {}
            return jsonify({
                "success":       True,
                "message":       "Profile saved successfully.",
                "username":      ur.get("username")    or fr.get("username", ""),
                "email":         ur.get("email", ""),
                "aadhaar":       ur.get("aadhaar_number", ""),
                "mobile":        fr.get("mobile_number", ""),
                "location":      fr.get("location", ""),
                "land_size":     fr.get("land_size"),
                "crop_type":     fr.get("crop_type", ""),
                "irrigation":    fr.get("irrigation_type", ""),
                "survey_number": fr.get("survey_number", ""),
            })

        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

    # =========================
    # HOME (landing before login)
    # =========================
    @app.route("/")
    def home():
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        return send_from_directory(frontend_dir, "home.html")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
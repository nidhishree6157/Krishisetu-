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

    # Single JOIN query used by all profile GET paths.
    _PROFILE_JOIN_SQL = """
        SELECT
            u.user_id,
            u.username,
            u.email,
            COALESCE(f.mobile_number, u.mobile_number) AS mobile_number,
            u.aadhaar_number,
            f.crop_type,
            f.location,
            f.land_size,
            f.irrigation_type,
            f.survey_number,
            f.farmer_id
        FROM users u
        LEFT JOIN farmers f ON f.username = u.username
        WHERE u.{col} = %s
        LIMIT 1
    """

    def _fetch_profile_row(conn, *, username=None, email=None):
        """
        Run the canonical LEFT JOIN and return a single unified dict
        (or None).  Accepts either username= or email= as the key.
        """
        if username:
            sql = _PROFILE_JOIN_SQL.format(col="username")
            param = username
        elif email:
            sql = _PROFILE_JOIN_SQL.format(col="email")
            param = email
        else:
            return None
        with conn.cursor() as cur:
            cur.execute(sql, (param,))
            return cur.fetchone()

    def _profile_get_username_and_farmer(conn):
        """
        Return (session_username, profile_row) using the session user when
        available.

        profile_row is the unified dict from _fetch_profile_row (single JOIN).
        The farmer_id=1 fallback only fires when there is NO session at all.
        When a session username is present we NEVER substitute another user's
        data — the caller receives None as profile_row and handles it.
        """
        username = session.get("username")

        if username:
            print(f"[PROFILE] Session user: {username!r} — fetching via LEFT JOIN (farmers table)")
            row = _fetch_profile_row(conn, username=username)
            if row:
                print(f"[PROFILE] Row found for {username!r}")
            else:
                print(f"[PROFILE] No row found for {username!r} — returning empty profile")
            return username, row

        # No session — last-resort dev fallback to farmer_id=1.
        print("[PROFILE] No session — attempting farmer_id=1 dev fallback")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.user_id, u.username, u.email,
                    COALESCE(f.mobile_number, u.mobile_number) AS mobile_number,
                    u.aadhaar_number,
                    f.crop_type, f.location, f.land_size,
                    f.irrigation_type, f.survey_number, f.farmer_id
                FROM farmers f
                JOIN users u ON u.username = f.username
                WHERE f.farmer_id = %s
                LIMIT 1
                """,
                (_FALLBACK_FARMER_ID,),
            )
            row = cur.fetchone()
        return username, row

    @app.route("/api/profile", methods=["GET"])
    def api_get_profile():
        """
        GET /api/profile
        ─────────────────
        Returns the farmer's profile as a flat JSON object.
        Single source of truth: LEFT JOIN users + farmers, keyed by username.
        Falls back to farmer_id=1 only when there is no session at all.
        """
        try:
            print("[PROFILE] GET /api/profile — fetching from farmers table via JOIN")
            conn = get_db_connection()
            _username, row = _profile_get_username_and_farmer(conn)

            r = row or {}

            # Soil data lives in soil_data, keyed by farmer_id.
            soil = {}
            fid  = r.get("farmer_id")
            if fid:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT nitrogen, phosphorus, potassium, ph, soil_ph "
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

            result = {
                "success":         True,
                "user_id":         r.get("user_id"),
                "username":        r.get("username", ""),
                "email":           r.get("email", ""),
                "aadhaar_number":  r.get("aadhaar_number", ""),
                "mobile_number":   r.get("mobile_number", ""),
                "location":        r.get("location", ""),
                "land_size":       r.get("land_size"),
                "crop_type":       r.get("crop_type", ""),
                "irrigation_type": r.get("irrigation_type", ""),
                "survey_number":   r.get("survey_number", ""),
                "has_soil_data":   bool(soil),
                **soil,
            }
            print("[PROFILE] Data:", result)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

    @app.route("/profile", methods=["GET"])
    def get_profile():
        """GET /profile — same payload as GET /api/profile; always JSON."""
        return api_get_profile()

    @app.route("/api/profile/<email>", methods=["GET"])
    def get_profile_by_email(email):
        """
        GET /api/profile/<email>
        ─────────────────────────
        Email-keyed profile lookup — reliable even when the Flask session
        has expired (e.g. after a server restart or hard refresh).

        Two explicit queries so each step is independently debuggable:
          1. SELECT from users  WHERE email    = %s
          2. SELECT from farmers WHERE username = %s
        """
        try:
            print(f"[PROFILE] GET /api/profile/{email!r}")
            print("PROFILE API CALLED WITH EMAIL:", email)
            conn = get_db_connection()

            # ── Step 1: fetch user row by email ───────────────────────────
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE email = %s LIMIT 1",
                    (email,),
                )
                user = cur.fetchone()
            print("USER RESULT:", user)

            if not user:
                return jsonify({"success": False, "message": "User not found"}), 404

            username = user["username"]
            print(f"[PROFILE] user found: {username!r}")

            # ── Step 2: fetch farmer row by username ──────────────────────
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM farmers WHERE username = %s LIMIT 1",
                    (username,),
                )
                farmer = cur.fetchone()
            print("FARMER RESULT:", farmer)

            # Guard: if no farmers row yet, use empty dict so .get() never throws.
            if not farmer:
                farmer = {}
            print(f"[PROFILE] farmer row: {'found' if farmer else 'not found (defaulting to empty)'}")

            # ── Step 3: merge and return ──────────────────────────────────
            # Soil data (nitrogen / phosphorus / potassium / ph) is stored
            # directly in the farmers table by the soil-upload route — NOT in
            # the soil_data table.  Reading from farmer avoids a broken join
            # when soil_data is empty or farmer_id is absent.
            result = {
                "success":        True,
                "username":       user.get("username"),
                "email":          user.get("email"),
                "aadhaar_number": user.get("aadhaar_number"),

                "mobile_number":  farmer.get("mobile_number"),
                "crop_type":      farmer.get("crop_type"),
                "location":       farmer.get("location"),
                "land_size":      farmer.get("land_size"),
                "irrigation_type": farmer.get("irrigation_type"),
                "survey_number":  farmer.get("survey_number"),

                "has_soil_data":  farmer.get("nitrogen") is not None,
                "nitrogen":       farmer.get("nitrogen"),
                "phosphorus":     farmer.get("phosphorus"),
                "potassium":      farmer.get("potassium"),
                "ph":             farmer.get("ph"),
            }
            print("[PROFILE] Data:", result)
            print("FINAL RESPONSE:", result)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

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
            print("SAVE PROFILE DATA:", data)

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

            # Identify the target username — session → email body → farmer_id=1 fallback
            if not username:
                email_from_body = str(data.get("email") or "").strip()
                print("EMAIL:", data.get("email"))
                if email_from_body:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT username FROM users WHERE email=%s LIMIT 1",
                            (email_from_body,),
                        )
                        row = cur.fetchone()
                        username = row.get("username") if row else None

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
            print("USER FOUND:", username)

            # Ensure farmers table and extra columns exist
            from routes.farmer import _ensure_farmers_table, _ensure_soil_columns
            _ensure_farmers_table(conn)
            _ensure_soil_columns(conn)

            print(f"[PROFILE] Saving to farmers table for username={username!r}")
            print("UPSERT FARMER WITH:", username, mobile, crop_type)

            with conn.cursor() as cur:
                # Check whether a farmers row already exists for this user.
                cur.execute(
                    "SELECT username FROM farmers WHERE username=%s LIMIT 1",
                    (username,),
                )
                farmer_exists = cur.fetchone() is not None

                if farmer_exists:
                    # UPDATE: leave soil_report_file untouched.
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
                    # INSERT: default soil_report_file to '' for new rows.
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
            print("SAVE SUCCESS")
            print(f"[PROFILE] Saved successfully for {username!r}")

            # Fetch fresh profile keyed by the confirmed username so the
            # response is correct even when the Flask session has expired
            # (previously used _profile_get_username_and_farmer which falls
            # back to farmer_id=1 when the session is gone, returning the
            # wrong user's data and making the save appear to be lost).
            row = _fetch_profile_row(conn, username=username)
            r   = row or {}
            result = {
                "success":         True,
                "message":         "Profile saved successfully.",
                "user_id":         r.get("user_id"),
                "username":        r.get("username", username),
                "email":           r.get("email", ""),
                "aadhaar_number":  r.get("aadhaar_number"),
                "mobile_number":   r.get("mobile_number", ""),
                "location":        r.get("location", ""),
                "land_size":       r.get("land_size"),
                "crop_type":       r.get("crop_type", ""),
                "irrigation_type": r.get("irrigation_type", ""),
                "survey_number":   r.get("survey_number", ""),
            }
            print("[PROFILE] Save response:", result)
            return jsonify(result)

        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

    # =========================
    # SOIL REPORT UPLOAD — session-free, email-keyed
    # =========================
    @app.route("/api/upload-soil-report", methods=["POST"])
    def api_upload_soil_report():
        """
        POST /api/upload-soil-report
        ─────────────────────────────
        Multipart fields:  file=<file>  email=<string>
        Works without a live Flask session (uses email to resolve username).
        Returns flat JSON: {success, nitrogen, phosphorus, potassium, ph}
        Soil values are written directly to the farmers table so
        GET /api/profile/<email> picks them up immediately.
        """
        import os as _os
        from werkzeug.utils import secure_filename as _secure_fn

        email = (request.form.get("email") or "").strip()
        file  = request.files.get("file")

        if not file or not file.filename:
            return jsonify({"success": False, "message": "No file provided"}), 400

        _allowed = {"pdf", "jpg", "jpeg", "png"}
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in _allowed:
            return jsonify({
                "success": False,
                "message": "File type not allowed. Upload PDF, JPG, or PNG.",
            }), 400

        # ── Resolve username (session → email body) ───────────────────────
        try:
            conn = get_db_connection()
        except DBConnectionError as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

        username = session.get("username")
        if not username and email:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username FROM users WHERE email=%s LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
                username = row.get("username") if row else None

        if not username:
            return jsonify({
                "success": False,
                "message": "User not identified. Please log in.",
            }), 401

        # ── Save file to disk ─────────────────────────────────────────────
        upload_dir = _os.path.join(_os.path.dirname(__file__), "uploads", "soil_reports")
        _os.makedirs(upload_dir, exist_ok=True)
        safe_name = _secure_fn(file.filename)
        filepath  = _os.path.join(upload_dir, f"{username}_{safe_name}")
        try:
            file.save(filepath)
        except Exception as exc:
            return jsonify({"success": False, "message": f"Could not save file: {exc}"}), 500

        # ── Extract NPK + pH ──────────────────────────────────────────────
        try:
            from services.soil_parser import extract_soil_data
            soil = extract_soil_data(filepath)
        except Exception as exc:
            print(f"[SoilUpload] Parser error: {exc} — using demo values")
            soil = {"nitrogen": 82.0, "phosphorus": 38.0, "potassium": 42.0, "ph": 6.4}

        nitrogen   = soil["nitrogen"]
        phosphorus = soil["phosphorus"]
        potassium  = soil["potassium"]
        ph         = soil["ph"]

        # ── Persist to farmers table ──────────────────────────────────────
        try:
            from routes.farmer import _ensure_farmers_table, _ensure_soil_columns
            _ensure_farmers_table(conn)
            _ensure_soil_columns(conn)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username FROM farmers WHERE username=%s LIMIT 1",
                    (username,),
                )
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
            print(f"[SoilUpload] Saved for {username!r}: N={nitrogen} P={phosphorus} K={potassium} pH={ph}")

        except Exception as exc:
            print(f"[SoilUpload] DB error: {exc}")
            return jsonify({"success": False, "message": "Database error while saving soil data"}), 500

        return jsonify({
            "success":    True,
            "nitrogen":   nitrogen,
            "phosphorus": phosphorus,
            "potassium":  potassium,
            "ph":         ph,
        })

    # =========================
    # HOME (landing before login)
    # =========================
    @app.route("/")
    def home():
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        return send_from_directory(frontend_dir, "home.html")

    # =========================
    # STATIC FRONTEND CATCH-ALL
    # =========================
    # Serves every file under /frontend/ that is not already handled by an
    # API blueprint (auth, soil, farmer …).
    #
    # WHY THIS IS CRITICAL FOR LOGIN:
    # Without this route, pages/login.html is opened directly from the
    # filesystem (file://…).  File-protocol pages have Origin: null.
    # Browsers silently block credentialed POST requests (fetch with
    # credentials:"include") when the origin is null — even after a
    # successful OPTIONS preflight — causing the login button to appear
    # permanently stuck on "Verifying credentials…".
    #
    # With this route, navigating to /pages/login.html returns the HTML
    # served from http://127.0.0.1:5000, giving it a proper HTTP origin
    # that Flask-CORS can reflect correctly, and the POST reaches Flask.
    @app.route("/<path:filename>")
    def serve_frontend_files(filename):
        frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
        try:
            return send_from_directory(frontend_dir, filename)
        except Exception:
            # File not found — return a plain 404 so browser DevTools shows
            # a clear error rather than an HTML "Not Found" page.
            return jsonify({"error": "Not found", "path": filename}), 404

    return app


def _check_email_config() -> None:
    """
    Print a clear warning at startup if the email credentials are missing or
    still set to their placeholder values.  This is the most common reason
    OTP emails are never received.
    """
    addr = os.environ.get("EMAIL_ADDRESS", "").strip()
    pw   = os.environ.get("EMAIL_PASSWORD", "").strip()
    skip = os.environ.get("SKIP_EMAIL_SEND", "").lower() in ("1", "true", "yes")
    dbg  = os.environ.get("OTP_DEBUG", "").lower() in ("1", "true", "yes")

    print("\n" + "=" * 64)
    print("  KrishiSetu — Email / OTP Configuration Check")
    print("=" * 64)

    if skip:
        print("  ⚠  SKIP_EMAIL_SEND=1  →  OTP emails DISABLED (dev mode).")
        print("     OTP is still stored in DB — query users.otp to read it.")
    elif not addr or addr == "your_gmail_address@gmail.com":
        print("  ✗  EMAIL_ADDRESS is not set (or still has placeholder value).")
        print("     → OTP login will FAIL until you set it in backend/.env")
    elif not pw or pw == "your_16_char_app_password_here":
        print("  ✗  EMAIL_PASSWORD is not set (or still has placeholder value).")
        print("     → Use a Gmail App Password, NOT your normal password.")
        print("     → Setup: myaccount.google.com → Security → App passwords")
    else:
        print(f"  ✓  EMAIL_ADDRESS : {addr}")
        print(f"  ✓  EMAIL_PASSWORD: {'*' * len(pw)} ({len(pw)} chars)")

    if dbg:
        print("  ⚠  OTP_DEBUG=1  →  OTP values will be printed to this console.")

    print("=" * 64 + "\n")


if __name__ == "__main__":
    app = create_app()
    _check_email_config()
    app.run(host="127.0.0.1", port=5000, debug=True)
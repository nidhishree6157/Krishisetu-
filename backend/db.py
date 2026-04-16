from __future__ import annotations

import threading
import time

import pymysql
from flask import current_app

# Requirement: ensure PyMySQL is used correctly
pymysql.install_as_MySQLdb()


class DBConnectionError(RuntimeError):
    pass


# Simple single-connection "pool" with reconnect safety.
_POOL_LOCK = threading.Lock()
_CACHED_CONN: pymysql.connections.Connection | None = None


def _bootstrap_schema(server_conn, db_name: str) -> None:
    """
    Ensures database + required tables exist.
    Expects `server_conn` to be connected to the MySQL server.
    """
    with server_conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}`")
        cur.execute(f"USE `{db_name}`")

        # Ensure username behaves as a unique identifier (needed for FK constraints).
        try:
            cur.execute("ALTER TABLE users ADD UNIQUE KEY uq_users_username (username)")
        except Exception:
            pass

        # Ensure OTP columns exist (otp + expiry timestamp).
        for col, ddl in (
            ("otp",            "ALTER TABLE users ADD COLUMN otp VARCHAR(6) NULL"),
            ("otp_expires_at", "ALTER TABLE users ADD COLUMN otp_expires_at DATETIME NULL"),
        ):
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users' AND COLUMN_NAME=%s
                    """,
                    (db_name, col),
                )
                r = cur.fetchone() or {}
                if int(r.get("cnt") or 0) == 0:
                    cur.execute(ddl)
            except Exception:
                pass

        # Ensure email column exists (OTP + account recovery).
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users' AND COLUMN_NAME='email'
                """,
                (db_name,),
            )
            row = cur.fetchone() or {}
            if int(row.get("cnt") or 0) == 0:
                cur.execute("ALTER TABLE users ADD COLUMN email VARCHAR(255) NULL")
        except Exception:
            pass

        # Registration: mobile + Aadhaar on users (shared by Farmer / Expert).
        for col, ddl in (
            ("mobile_number", "ALTER TABLE users ADD COLUMN mobile_number VARCHAR(20) NULL"),
            ("aadhaar_number", "ALTER TABLE users ADD COLUMN aadhaar_number CHAR(12) NULL"),
        ):
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users' AND COLUMN_NAME=%s
                    """,
                    (db_name, col),
                )
                row = cur.fetchone() or {}
                if int(row.get("cnt") or 0) == 0:
                    cur.execute(ddl)
            except Exception:
                pass

        for idx_name, col in (
            ("uq_users_mobile", "mobile_number"),
            ("uq_users_aadhaar", "aadhaar_number"),
        ):
            try:
                cur.execute(
                    f"CREATE UNIQUE INDEX {idx_name} ON users ({col})"
                )
            except Exception:
                pass

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              user_id INT NOT NULL AUTO_INCREMENT,
              username VARCHAR(100) NOT NULL UNIQUE,
              email VARCHAR(255) NOT NULL UNIQUE,
              password VARCHAR(255) NOT NULL,
              otp VARCHAR(6) NULL DEFAULT NULL,
              otp_expires_at DATETIME NULL DEFAULT NULL,
              user_role VARCHAR(50) NOT NULL DEFAULT 'Farmer',
              mobile_number VARCHAR(20) NULL,
              aadhaar_number CHAR(12) NULL,
              PRIMARY KEY (user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS farmer_profiles (
              id INT NOT NULL AUTO_INCREMENT,
              user_id INT NOT NULL,
              mobile_number VARCHAR(20) NOT NULL,
              crop_type VARCHAR(100) NOT NULL,
              location VARCHAR(255) NOT NULL,
              land_size DECIMAL(10,2) NOT NULL,
              irrigation_type VARCHAR(100) NOT NULL,
              PRIMARY KEY (id),
              UNIQUE KEY uq_farmer_profiles_user_id (user_id),
              CONSTRAINT fk_farmer_profiles_user_id
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Module 2: one-to-one farmer profile keyed by `users.username`.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS farmers (
              farmer_id INT NOT NULL AUTO_INCREMENT,
              username VARCHAR(100) NOT NULL,
              mobile_number VARCHAR(20) NOT NULL,
              crop_type VARCHAR(100) NOT NULL,
              location VARCHAR(255) NOT NULL,
              land_size DECIMAL(10,2) NOT NULL,
              irrigation_type VARCHAR(100) NOT NULL,
              survey_number VARCHAR(100) NOT NULL,
              soil_report_file TEXT NOT NULL,
              PRIMARY KEY (username),
              UNIQUE KEY uq_farmers_farmer_id (farmer_id),
              CONSTRAINT fk_farmers_username
                FOREIGN KEY (username) REFERENCES users(username)
                ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Best-effort: if farmers table already exists without farmer_id, add it.
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME='farmers' AND COLUMN_NAME='farmer_id'
                """,
                (db_name,),
            )
            row = cur.fetchone() or {}
            if int(row.get("cnt") or 0) == 0:
                cur.execute(
                    "ALTER TABLE farmers ADD COLUMN farmer_id INT NOT NULL AUTO_INCREMENT"
                )
                # Ensure farmer_id is indexed so soil_data FK can work.
                try:
                    cur.execute("ALTER TABLE farmers ADD UNIQUE KEY uq_farmers_farmer_id (farmer_id)")
                except Exception:
                    pass
        except Exception:
            pass

        # Best-effort: add soil-related columns to farmers so POST /soil/data can UPDATE them.
        for col, ddl in (
            ("nitrogen",               "ALTER TABLE farmers ADD COLUMN nitrogen DECIMAL(10,2) NULL DEFAULT 0"),
            ("phosphorus",             "ALTER TABLE farmers ADD COLUMN phosphorus DECIMAL(10,2) NULL DEFAULT 0"),
            ("potassium",              "ALTER TABLE farmers ADD COLUMN potassium DECIMAL(10,2) NULL DEFAULT 0"),
            ("ph",                     "ALTER TABLE farmers ADD COLUMN ph DECIMAL(4,2) NULL DEFAULT 0"),
            ("organic_matter",         "ALTER TABLE farmers ADD COLUMN organic_matter DECIMAL(10,2) NULL DEFAULT 0"),
            ("electrical_conductivity","ALTER TABLE farmers ADD COLUMN electrical_conductivity DECIMAL(10,4) NULL DEFAULT 0"),
            ("soil_type",              "ALTER TABLE farmers ADD COLUMN soil_type VARCHAR(100) NULL DEFAULT ''"),
        ):
            try:
                cur.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=%s AND TABLE_NAME='farmers' AND COLUMN_NAME=%s
                    """,
                    (db_name, col),
                )
                r = cur.fetchone() or {}
                if int(r.get("cnt") or 0) == 0:
                    cur.execute(ddl)
            except Exception:
                pass

        # Module 2: one-to-one expert profile keyed by `users.username`.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experts (
              username VARCHAR(100) NOT NULL,
              mobile_number VARCHAR(20) NOT NULL,
              expertise_field VARCHAR(100) NOT NULL,
              experience_years INT NOT NULL,
              qualification TEXT NOT NULL,
              qualification_file TEXT NULL,
              PRIMARY KEY (username),
              CONSTRAINT fk_experts_username
                FOREIGN KEY (username) REFERENCES users(username)
                ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Best-effort: ensure experts has `expert_id` so expert_queries can FK to it.
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME='experts' AND COLUMN_NAME='expert_id'
                """,
                (db_name,),
            )
            row = cur.fetchone() or {}
            if int(row.get("cnt") or 0) == 0:
                # Create auto-incrementing expert_id with uniqueness for FK compatibility.
                cur.execute(
                    """
                    ALTER TABLE experts
                      ADD COLUMN expert_id INT NOT NULL AUTO_INCREMENT,
                      ADD UNIQUE KEY uq_experts_expert_id (expert_id)
                    """
                )
        except Exception:
            # If ALTER fails due to existing structure, leave it to runtime errors.
            pass

        # Expert consultation module queries (farmer-expert communication).
        # Requirement columns:
        # - query_id PK auto increment
        # - farmer_id FK -> farmers.farmer_id
        # - expert_id FK -> experts.expert_id NULL allowed
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS expert_queries (
                  query_id INT NOT NULL AUTO_INCREMENT,
                  farmer_id INT NOT NULL,
                  expert_id INT NULL,
                  query_text TEXT NOT NULL,
                  query_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  expert_response TEXT NULL,
                  response_date DATETIME NULL,
                  status VARCHAR(20) NOT NULL DEFAULT 'Pending',
                  PRIMARY KEY (query_id),
                  CONSTRAINT fk_expert_queries_farmer_id
                    FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id)
                    ON DELETE CASCADE,
                  CONSTRAINT fk_expert_queries_expert_id
                    FOREIGN KEY (expert_id) REFERENCES experts(expert_id)
                    ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
        except Exception:
            # Best-effort fallback: create table without FK constraints
            # (keeps app bootstrapping even if schema migrations can't be applied).
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS expert_queries (
                  query_id INT NOT NULL AUTO_INCREMENT,
                  farmer_id INT NOT NULL,
                  expert_id INT NULL,
                  query_text TEXT NOT NULL,
                  query_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  expert_response TEXT NULL,
                  response_date DATETIME NULL,
                  status VARCHAR(20) NOT NULL DEFAULT 'Pending',
                  PRIMARY KEY (query_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )

        # Soil Data Module
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS soil_data (
              farmer_id INT NOT NULL,
              soil_ph DECIMAL(4,2) NOT NULL,
              nitrogen DECIMAL(10,2) NOT NULL,
              phosphorus DECIMAL(10,2) NOT NULL,
              potassium DECIMAL(10,2) NOT NULL,
              organic_carbon DECIMAL(10,2) NOT NULL,
              PRIMARY KEY (farmer_id),
              CONSTRAINT fk_soil_data_farmer_id
                FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id)
                ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Market price module
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS market_prices (
              price_id INT NOT NULL AUTO_INCREMENT,
              crop_name VARCHAR(100) NOT NULL,
              market_location VARCHAR(255) NOT NULL,
              price DECIMAL(12,2) NOT NULL,
              price_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (price_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Government schemes module
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS government_schemes (
              scheme_id INT NOT NULL AUTO_INCREMENT,
              scheme_name VARCHAR(255) NOT NULL,
              description TEXT NOT NULL,
              eligibility TEXT NOT NULL,
              last_date DATE NOT NULL,
              PRIMARY KEY (scheme_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Activity scheduler module
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_schedule (
              schedule_id INT NOT NULL AUTO_INCREMENT,
              farmer_id INT NOT NULL,
              activity_type VARCHAR(100) NOT NULL,
              activity_date DATE NOT NULL,
              reminder VARCHAR(20) NULL,
              PRIMARY KEY (schedule_id),
              CONSTRAINT fk_activity_schedule_farmer_id
                FOREIGN KEY (farmer_id) REFERENCES farmers(farmer_id)
                ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Disease alerts module (notification source)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS disease_alerts (
              alert_id   INT NOT NULL AUTO_INCREMENT,
              farmer_id  INT NOT NULL,
              disease_name VARCHAR(200) NOT NULL,
              alert_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (alert_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )

        # Best-effort: add alert_id to existing disease_alerts if missing
        try:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM   information_schema.COLUMNS
                WHERE  TABLE_SCHEMA=%s
                  AND  TABLE_NAME='disease_alerts'
                  AND  COLUMN_NAME='alert_id'
                """,
                (db_name,),
            )
            r = cur.fetchone() or {}
            if int(r.get("cnt") or 0) == 0:
                cur.execute(
                    "ALTER TABLE disease_alerts "
                    "ADD COLUMN alert_id INT NOT NULL AUTO_INCREMENT FIRST, "
                    "ADD PRIMARY KEY (alert_id)"
                )
        except Exception:
            pass

        # Notification read-state tracker
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications_read (
              id               INT NOT NULL AUTO_INCREMENT,
              session_user     VARCHAR(100) NOT NULL,
              notification_ref VARCHAR(150) NOT NULL,
              read_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uq_notif_read (session_user, notification_ref)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )


def _new_connection() -> pymysql.connections.Connection:
    """
    Create a new live PyMySQL connection using app config.

    Timeout parameters (all in seconds):
      connect_timeout — how long to wait for the TCP handshake before giving
                        up.  Without this, Windows uses the OS default (up to
                        120 s), causing the login route to appear "stuck at
                        Checking DB…" for minutes.
      read_timeout    — max time to wait for MySQL to send data after a query.
      write_timeout   — max time to wait for MySQL to accept a write.
    """
    if not current_app:
        raise DBConnectionError("No Flask app context available for DB connection")

    cfg = current_app.config
    print(f"[DB] Connecting to MySQL at {cfg['MYSQL_HOST']}:{cfg['MYSQL_PORT']} ...")
    return pymysql.connect(
        host=cfg["MYSQL_HOST"],
        user=cfg["MYSQL_USER"],
        password=cfg["MYSQL_PASSWORD"],
        database=cfg["MYSQL_DB"],
        port=int(cfg["MYSQL_PORT"]),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=5,   # fail fast if MySQL is unreachable
        read_timeout=10,     # abort if a query result takes > 10 s
        write_timeout=10,    # abort if a write takes > 10 s
    )


def get_db_connection() -> pymysql.connections.Connection:
    """
    Returns a live PyMySQL connection object.
    Never returns None. On connection failure, raises DBConnectionError.
    Includes retry/reconnect logic.
    """
    global _CACHED_CONN

    print("[DB] get_db_connection() called")
    with _POOL_LOCK:
        # ── Reuse cached connection if still alive ───────────────────────────
        if _CACHED_CONN is not None:
            try:
                if not getattr(_CACHED_CONN, "open", True):
                    raise DBConnectionError("Cached connection is closed")
                # ping() respects the read/write_timeout set on the socket, so
                # it cannot hang indefinitely even on a stale half-open socket.
                _CACHED_CONN.ping(reconnect=True)
                print("[DB] Reusing cached connection")
                return _CACHED_CONN
            except Exception as ping_err:
                print(f"[DB] Cached connection stale ({ping_err}), reconnecting …")
                try:
                    _CACHED_CONN.close()
                except Exception:
                    pass
                _CACHED_CONN = None

        # ── Establish a new connection (up to 3 attempts) ────────────────────
        last_err: Exception | None = None
        conn: pymysql.connections.Connection | None = None
        for attempt in range(1, 4):
            print(f"[DB] Connection attempt {attempt}/3 …")
            try:
                conn = _new_connection()
                print("[DB] Connected to MySQL ✓")
                break
            except pymysql.MySQLError as e:
                last_err = e
                print(f"[DB] MySQL error on attempt {attempt}: {e}")
                code = None
                try:
                    code = getattr(e, "args", [None])[0]
                except Exception:
                    code = None

                if code == 1049:  # Unknown database — bootstrap schema first
                    print(f"[DB] Database not found (1049). Bootstrapping schema …")
                    try:
                        cfg = current_app.config
                        server_conn = pymysql.connect(
                            host=cfg["MYSQL_HOST"],
                            user=cfg["MYSQL_USER"],
                            password=cfg["MYSQL_PASSWORD"],
                            port=int(cfg["MYSQL_PORT"]),
                            charset="utf8mb4",
                            cursorclass=pymysql.cursors.DictCursor,
                            autocommit=True,
                            connect_timeout=5,
                        )
                        try:
                            _bootstrap_schema(server_conn, cfg["MYSQL_DB"])
                            print("[DB] Schema bootstrapped ✓")
                        finally:
                            try:
                                server_conn.close()
                            except Exception:
                                pass
                    except pymysql.MySQLError as ee:
                        raise DBConnectionError(f"MySQL bootstrap failed: {ee}") from ee
                time.sleep(0.25 * attempt)
            except Exception as e:
                last_err = e
                print(f"[DB] Unexpected error on attempt {attempt}: {e}")
                time.sleep(0.25 * attempt)

        if conn is None:
            cfg = current_app.config if current_app else {}
            target = (
                f"user='{cfg.get('MYSQL_USER')}', host='{cfg.get('MYSQL_HOST')}', "
                f"port='{cfg.get('MYSQL_PORT')}', db='{cfg.get('MYSQL_DB')}'"
            )
            err_msg = f"MySQL connection failed for {target}: {last_err}"
            print(f"[DB] ✗ {err_msg}")
            raise DBConnectionError(err_msg)

        # ── Ensure tables exist (runs once per new connection) ───────────────
        print("[DB] Running schema bootstrap …")
        try:
            cfg = current_app.config
            _bootstrap_schema(conn, cfg["MYSQL_DB"])
            print("[DB] Schema ready ✓")
        except Exception as bs_err:
            # Non-fatal: return the connection anyway; route code surfaces SQL errors.
            print(f"[DB] Schema bootstrap warning: {bs_err}")

        _CACHED_CONN = conn
        return conn


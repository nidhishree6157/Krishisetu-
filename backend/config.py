import os

from dotenv import load_dotenv

# Load backend/.env once at import time (no-op if file is absent).
_ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=_ENV_PATH, override=False)


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "change-me-in-production")

    # ── Database ────────────────────────────────────────────────────────────
    MYSQL_HOST     = os.environ.get("MYSQL_HOST",     "127.0.0.1")
    MYSQL_USER     = os.environ.get("MYSQL_USER",     "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_DB       = os.environ.get("MYSQL_DB",       "agriculture_db")
    MYSQL_PORT     = int(os.environ.get("MYSQL_PORT", "3306"))

    # Backwards-compatible aliases kept for db.py.
    DB_HOST     = MYSQL_HOST
    DB_USER     = MYSQL_USER
    DB_PASSWORD = MYSQL_PASSWORD
    DB_NAME     = MYSQL_DB
    DB_PORT     = MYSQL_PORT

    # ── Email / OTP ─────────────────────────────────────────────────────────
    # Set these in backend/.env — never commit real values.
    # Gmail: enable 2-Step Verification, create an App Password, paste it below.
    EMAIL_ADDRESS  = os.environ.get("EMAIL_ADDRESS",  "")
    EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")   # Gmail App Password

    OTP_EXPIRY_MINUTES = int(os.environ.get("OTP_EXPIRY_MINUTES", "5"))

    # ── Session ─────────────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # SESSION_COOKIE_SECURE = True   # enable behind HTTPS in production

    # ── File uploads ────────────────────────────────────────────────────────
    UPLOAD_FOLDER       = "uploads/expert_docs"
    ALLOWED_EXTENSIONS  = {"png", "jpg", "jpeg", "pdf"}

    @staticmethod
    def allowed_file(filename: str) -> bool:
        return (
            "." in filename
            and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS
        )


# Module-level aliases kept for backward compatibility with existing imports.
UPLOAD_FOLDER      = Config.UPLOAD_FOLDER
ALLOWED_EXTENSIONS = Config.ALLOWED_EXTENSIONS
allowed_file       = Config.allowed_file

"""
KrishiSetu — Email OTP service.

Credentials are read from backend/.env (loaded by app.py and here as a fallback):
    EMAIL_ADDRESS   — your Gmail address
    EMAIL_PASSWORD  — Gmail App Password (16 chars, no spaces)

Set SKIP_EMAIL_SEND=1 in .env to bypass SMTP in dev/testing
(OTP is still stored in DB so you can test verify-otp manually).
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

# Fallback load so the module works even when imported before app.py runs.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587           # TLS via STARTTLS


def send_otp_email(to_email: str, otp: str, expiry_minutes: int = 5) -> None:
    """
    Send a login OTP to `to_email` via Gmail SMTP (port 587, STARTTLS).

    Raises RuntimeError  — missing credentials.
    Raises smtplib.*     — SMTP / network failure.
    The caller (login route) catches both and rolls back the stored OTP.
    """
    # ── dev / CI bypass ─────────────────────────────────────────────────────
    if os.environ.get("SKIP_EMAIL_SEND", "").lower() in ("1", "true", "yes"):
        print(f"[OTP] SKIP_EMAIL_SEND is set — email not sent to {to_email}")
        logger.warning("[OTP] SKIP_EMAIL_SEND active — email not sent to %s", to_email)
        return

    from_addr    = os.environ.get("EMAIL_ADDRESS",  "").strip()
    app_password = os.environ.get("EMAIL_PASSWORD", "").strip()

    if not from_addr or not app_password:
        raise RuntimeError(
            "EMAIL_ADDRESS and EMAIL_PASSWORD must be set in backend/.env. "
            "Use a Gmail App Password, not your normal password."
        )

    # ── debug print (visible in terminal) ───────────────────────────────────
    print(f"Sending OTP to: {to_email}")

    subject   = "Your OTP Code"
    text_body = (
        f"Hello,\n\n"
        f"Your KrishiSetu OTP is: {otp}\n\n"
        f"This code expires in {expiry_minutes} minute(s).\n"
        f"Do not share it with anyone.\n\n"
        f"— KrishiSetu Team"
    )
    html_body = f"""\
<html>
<body style="font-family:sans-serif;color:#1a1a1a;max-width:480px;margin:auto;">
  <h2 style="color:#2e7d32;">KrishiSetu — Login Verification</h2>
  <p>Use the one-time code below to complete your login.</p>
  <p style="font-size:36px;font-weight:700;letter-spacing:10px;
            color:#2e7d32;background:#f0fdf4;
            padding:16px 24px;border-radius:8px;display:inline-block;">
    {otp}
  </p>
  <p>
    Expires in <strong>{expiry_minutes} minute(s)</strong>.<br>
    Never share this code with anyone.
  </p>
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
  <p style="font-size:12px;color:#9ca3af;">
    If you did not try to log in, ignore this email.
  </p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"KrishiSetu <{from_addr}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    print(f"[OTP] Connecting to {_SMTP_HOST}:{_SMTP_PORT} ...")
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as server:
            server.ehlo()
            server.starttls()          # upgrade to TLS
            server.ehlo()
            server.login(from_addr, app_password)
            server.sendmail(from_addr, to_email, msg.as_string())

        print(f"[OTP] ✓ OTP sent successfully to: {to_email}")
        logger.info("[OTP] OTP sent to: %s", to_email)

    except smtplib.SMTPAuthenticationError:
        print("[OTP] ✗ Authentication failed. Check EMAIL_ADDRESS and EMAIL_PASSWORD in .env")
        logger.error("[OTP] SMTP auth failed for sender %s", from_addr)
        raise
    except smtplib.SMTPException as exc:
        print(f"[OTP] ✗ SMTP error: {exc}")
        logger.error("[OTP] SMTP error sending to %s: %s", to_email, exc)
        raise
    except OSError as exc:
        print(f"[OTP] ✗ Network error: {exc}")
        logger.error("[OTP] Network error sending to %s: %s", to_email, exc)
        raise

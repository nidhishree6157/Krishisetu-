def generate_otp() -> str:
    """
    Generate a cryptographically adequate 6-digit OTP.

    Set OTP_DEBUG=1 in backend/.env to print the OTP to the console during
    local development.  NEVER enable this in production.
    """
    import os
    import random

    otp = str(random.randint(100000, 999999))

    if os.environ.get("OTP_DEBUG", "").strip() in ("1", "true", "yes"):
        print(f"[OTP] *** DEBUG *** Generated OTP: {otp}  "
              f"← disable OTP_DEBUG in production!")

    return otp

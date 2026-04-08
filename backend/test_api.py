import json
import sys
import time
import uuid
from typing import Any

BASE_URL = "http://127.0.0.1:5000"


def _require_requests() -> bool:
    try:
        import requests  # noqa: F401

        return True
    except Exception:
        print("Missing dependency: requests")
        print("Install it with:")
        print("  python -m pip install requests")
        return False


def _print_response(title: str, resp: Any) -> None:
    print("\n" + "=" * 80)
    print(title)
    print(f"STATUS CODE: {getattr(resp, 'status_code', 'N/A')}")
    try:
        data = resp.json()
        print("RESPONSE JSON:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        try:
            print("RESPONSE TEXT:")
            print(resp.text)
        except Exception:
            print("RESPONSE: <unavailable>")


def _safe_post(s, url: str, payload: dict, timeout: int = 15):
    try:
        return s.post(url, json=payload, timeout=timeout)
    except Exception as e:
        print(f"\nERROR: POST {url} failed: {e}")
        return None


def _safe_get(s, url: str, timeout: int = 15):
    try:
        return s.get(url, timeout=timeout)
    except Exception as e:
        print(f"\nERROR: GET {url} failed: {e}")
        return None


def _fetch_otp_from_db(flask_app, username: str) -> str | None:
    """
    Test-only helper: reads OTP directly from DB so we can call /auth/verify-otp.
    Uses Flask app context because get_db_connection relies on current_app config.
    """
    from db import get_db_connection

    with flask_app.app_context():
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT otp FROM users WHERE username=%s LIMIT 1", (username,))
            row = cur.fetchone() or {}
            otp = row.get("otp")
            return None if otp is None else str(otp)


def create_farmer_profile(s) -> None:
    url = f"{BASE_URL}/farmer/profile"
    payload = {
        "mobile_number": "9876543210",
        "crop_type": "Rice",
        "location": "Karnataka",
        "land_size": 2.5,
        "irrigation_type": "Drip",
        # Optional fields (allowed by current SRS update)
        "survey_number": "SN-101",
        "soil_report_file": "soil.txt",
    }
    r = _safe_post(s, url, payload)
    if r is None:
        sys.exit(1)
    _print_response("STEP 5: Create Farmer Profile (POST /farmer/profile)", r)

def test_weather(s):
    url = f"{BASE_URL}/weather?city=Mangalore"

    res = _safe_get(s, url)

    print("\nSTEP: Weather")
    print("STATUS:", res.status_code)
    print("RESPONSE:", res.text)

def add_soil_data(s) -> None:
    url = f"{BASE_URL}/soil/data"

    payload = {
        "soil_ph": 6.5,
        "nitrogen": 20,
        "phosphorus": 10,
        "potassium": 10,
        "organic_carbon": 0.2,
    }

    r = _safe_post(s, url, payload)
    if r is None:
        sys.exit(1)
    _print_response("STEP 6: Add Soil Data (POST /soil/data)", r)


def get_ai_recommendation(s) -> None:
    url = f"{BASE_URL}/ai/crop-recommendation"

    # AI module is DB-integrated now; payload can be empty.
    r = _safe_post(s, url, {})
    if r is None:
        sys.exit(1)
    _print_response("STEP 7: AI Recommendation (POST /ai/crop-recommendation)", r)

def add_crop(s) -> None:
    url = f"{BASE_URL}/crop/add"
    payload = {
        "crop_name": "Rice",
        "planting_date": "2026-03-01",
        "expected_harvest": "2026-06-01",
    }
    r = _safe_post(s, url, payload)
    if r is None:
        sys.exit(1)
    _print_response("STEP 8: Add Crop (POST /crop/add)", r)


def get_crops(s) -> None:
    url = f"{BASE_URL}/crop/list"
    r = _safe_get(s, url)
    if r is None:
        sys.exit(1)
    _print_response("STEP 9: Get Crops (GET /crop/list)", r)

def test_expert_query(s):
    url = f"{BASE_URL}/expert/query"

    data = {
        "query_text": "My crop leaves are yellow. What should I do?"
    }

    res = _safe_post(s, url, data)

    print("\nSTEP: Expert Query")
    print("STATUS:", res.status_code)
    print("RESPONSE:", res.text)

def test_activity(s):
    # Add activity
    r = _safe_post(s, f"{BASE_URL}/activity/add", {
        "activity_type": "Irrigation",
        "activity_date": "2026-04-01",
        "reminder": "Yes"
    })

    print("\nSTEP: Add Activity")
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

    # Get activities
    r = _safe_get(s, f"{BASE_URL}/activity/list")

    print("\nSTEP: Get Activities")
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

def test_fertilizer(s):
    url = f"{BASE_URL}/fertilizer/recommend"

    res = _safe_get(s, url)

    print("\nSTEP: Fertilizer Recommendation")
    print("STATUS:", res.status_code)
    print("RESPONSE:", res.text)

def test_pest(s):
    url = f"{BASE_URL}/pest/recommend"

    data = {
        "crop": "Rice",
        "symptom": "yellow leaves"
    }

    r = _safe_post(s, url, data)

    print("\nSTEP: Pest Recommendation")
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

def test_disease(s):
    url = f"{BASE_URL}/disease/predict"

    files = {
        "image": open("test.jpg", "rb")  # make sure file exists
    }

    try:
        res = s.post(url, files=files)
        print("\nSTEP: Disease Prediction")
        print("STATUS:", res.status_code)
        print("RESPONSE:", res.text)
    except Exception as e:
        print("Error:", e)

def test_alerts(s):
    res = _safe_get(s, f"{BASE_URL}/disease/alerts")
    print("\nSTEP: Disease Alerts", res.text)

def test_market(s):
    # Add price
    r = _safe_post(s, f"{BASE_URL}/market/add", {
        "crop_name": "Rice",
        "market_location": "Mangalore",
        "price": 2500
    })
    print("\nSTEP: Add Market Price")
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

    # Get prices
    r = _safe_get(s, f"{BASE_URL}/market/prices?crop_name=Rice")
    print("\nSTEP: Get Market Prices")
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

def test_market_api(s):
    url = f"{BASE_URL}/market/prices?crop_name=Rice"

    res = _safe_get(s, url)

    print("\nSTEP: Market (API + DB)")
    print("STATUS:", res.status_code)
    print("RESPONSE:", res.text)

def test_schemes(s):
    _safe_post(s, f"{BASE_URL}/schemes/add", {
        "scheme_name": "PM Kisan",
        "description": "Financial support",
        "eligibility": "All farmers",
        "last_date": "2026-12-31"
    })

    r = _safe_get(s, f"{BASE_URL}/schemes/all")

    print("\nSTEP: Schemes")
    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

def logout(s) -> None:
    url = f"{BASE_URL}/auth/logout"
    r = _safe_post(s, url, {})
    if r is None:
        sys.exit(1)
    _print_response("STEP 10: Logout (POST /auth/logout)", r)


def main():
    if not _require_requests():
        sys.exit(1)

    import requests

    unique = uuid.uuid4().hex[:8]
    email = f"user_{unique}@example.com"
    password = "Test@12345"
    username = f"user_{unique}"
    uid_num = uuid.uuid4().int
    test_mobile = f"{uid_num % (10**10):010d}"
    test_aadhaar = f"{uid_num % (10**12):012d}"

    s = requests.Session()

    print("Starting automated API flow (OTP + Farmer + Crops) against:", BASE_URL)
    print("Test user:", f"{username} / {email}")

    import app as appmod
    flask_app = appmod.create_app()

    # STEP 1: Register (full farmer payload required by /auth/register)
    r = _safe_post(
        s,
        f"{BASE_URL}/auth/register",
        {
            "username": username,
            "email": email,
            "password": password,
            "confirm_password": password,
            "mobile_number": test_mobile,
            "aadhaar_number": test_aadhaar,
            "role": "Farmer",
            "crop_type": "Rice",
            "location": "Karnataka",
            "land_size": 2.5,
        },
    )
    if r is None:
        sys.exit(1)
    _print_response("STEP 1: Register (POST /auth/register)", r)

    # STEP 2: Login — validates password and stores OTP (email send may be skipped in dev)
    r = _safe_post(
        s,
        f"{BASE_URL}/auth/login",
        {"username": username, "password": password},
    )
    if r is None:
        sys.exit(1)
    _print_response("STEP 2: Login / request OTP (POST /auth/login)", r)

    otp = _fetch_otp_from_db(flask_app, username)
    print("\n" + "=" * 80)
    print("STEP 3: OTP (test-only, read from DB)")
    print("OTP:", otp)
    if not otp:
        print(
            "ERROR: OTP not found. Check DB and that /auth/login returned success (OTP sent)."
        )
        sys.exit(1)

    # STEP 4: Verify OTP — establishes session
    r = _safe_post(s, f"{BASE_URL}/auth/verify-otp", {"username": username, "otp": otp})
    if r is None:
        sys.exit(1)
    _print_response("STEP 4: Verify OTP + session (POST /auth/verify-otp)", r)

    print("\nSession cookies stored:", len(getattr(s, "cookies", [])))

    # STEP 5-10: Farmer profile + soil + AI + crops (authenticated)
    create_farmer_profile(s)
    test_weather(s)
    add_soil_data(s)
    get_ai_recommendation(s)
    add_crop(s)
    get_crops(s)
    test_expert_query(s)
    test_activity(s)
    test_fertilizer(s)
    test_pest(s)
    test_disease(s)
    test_alerts(s)
    test_market(s)
    test_market_api(s)
    test_schemes(s)
    logout(s)

    print("\n" + "=" * 80)
    print("DONE: Flow finished.")
    print("=" * 80)


if __name__ == "__main__":
    try:
        start = time.time()
        main()
        print(f"\nTotal time: {time.time() - start:.2f}s")
    except KeyboardInterrupt:
        print("\nInterrupted.")

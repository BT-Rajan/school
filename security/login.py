"""Sign in as a staging admin and print the session cookie and CSRF token for ZAP.

Usage: SCAN_EMAIL=... SCAN_PASSWORD=... SCAN_TOTP_SECRET=... python login.py https://staging.example.org
"""

import json
import os
import sys

import httpx
import pyotp

with httpx.Client(base_url=sys.argv[1], verify=os.environ.get("SCAN_VERIFY_TLS", "1") == "1", trust_env=False) as c:
    start = c.post("/api/auth/login", json={"email": os.environ["SCAN_EMAIL"], "password": os.environ["SCAN_PASSWORD"]})
    start.raise_for_status()
    code = pyotp.TOTP(os.environ["SCAN_TOTP_SECRET"]).now()
    c.post("/api/auth/login/verify", json={"challenge": start.json()["challenge"], "code": code}).raise_for_status()
    print(json.dumps({"session": c.cookies["sces_session"], "csrf": c.cookies["sces_csrf"]}))

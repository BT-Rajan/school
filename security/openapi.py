"""The API description for an OWASP ZAP API scan, from the app itself.

Production builds do not publish it, so it is written from the code. The endpoints that would
end the scan's own session, or lock its account, are left out; they have their own abuse tests
(backend/tests/test_auth.py).

Usage, from backend/ with the app's environment set:
  .venv/bin/python ../security/openapi.py https://staging.example.org openapi.json
"""

import json
import sys

from app.main import create_app

SKIP = (
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/sessions",
    "/api/auth/password",
    "/api/auth/mfa",
    "/api/auth/recovery-codes",
    "/api/auth/invitations",
    "/api/admin/support-sessions",
)

spec = create_app().openapi()
spec["servers"] = [{"url": sys.argv[1]}]
spec["paths"] = {p: v for p, v in spec["paths"].items() if not p.startswith(SKIP) and "/deactivate" not in p}
with open(sys.argv[2], "w") as f:
    json.dump(spec, f)
print(len(spec["paths"]), "paths")

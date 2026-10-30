#!/usr/bin/env bash
# Release security scan (section 19): OWASP ZAP baseline of the web app, then an active scan of
# every API endpoint signed in as a staging admin. Never run it against production: the active
# scan sends attack payloads and creates records.
#   SCAN_EMAIL=... SCAN_PASSWORD=... SCAN_TOTP_SECRET=... security/zap.sh https://staging.example.org reports/
# Run from the repository, with backend/.venv set up and the app's environment exported
# (SCES_SECRET_KEY and SCES_ENCRYPTION_KEY are needed only to build the API description).
set -euo pipefail
url="${1:?staging URL}"
out="$(realpath "${2:?output directory}")"
mkdir -p "$out" && chmod 777 "$out"
image=ghcr.io/zaproxy/zaproxy:stable
host="${url#https://}"; host="${host%%/*}"

(cd backend && .venv/bin/python ../security/openapi.py "$url" "$out/openapi.json")

echo "== baseline"
docker run --rm --network host -v "$out:/zap/wrk" "$image" zap-baseline.py -t "$url/" -r baseline.html -J baseline.json -I -m 3 | tail -3

auth=$(backend/.venv/bin/python security/login.py "$url")
session=$(python3 -c "import json,sys;print(json.loads(sys.argv[1])['session'])" "$auth")
csrf=$(python3 -c "import json,sys;print(json.loads(sys.argv[1])['csrf'])" "$auth")
replace="-config replacer.full_list(0).description=cookie -config replacer.full_list(0).enabled=true"
replace+=" -config replacer.full_list(0).matchtype=REQ_HEADER -config replacer.full_list(0).matchstr=Cookie"
replace+=" -config replacer.full_list(0).regex=false -config replacer.full_list(0).replacement=sces_session=$session;sces_csrf=$csrf"
replace+=" -config replacer.full_list(1).description=csrf -config replacer.full_list(1).enabled=true"
replace+=" -config replacer.full_list(1).matchtype=REQ_HEADER -config replacer.full_list(1).matchstr=X-CSRF-Token"
replace+=" -config replacer.full_list(1).regex=false -config replacer.full_list(1).replacement=$csrf"

echo "== api scan, signed in"
docker run --rm --network host -v "$out:/zap/wrk" "$image" zap-api-scan.py \
  -t /zap/wrk/openapi.json -f openapi -r api.html -J api.json -I -T 60 -z "$replace" | tail -3
echo "reports: $out/baseline.html $out/api.html"
echo "host: $host"

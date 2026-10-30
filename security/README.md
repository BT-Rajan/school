# Release security checks

Before each release (requirements section 19), on a **staging copy**, never on production:

1. `zap.sh`: OWASP ZAP, a passive baseline of the web app and an active scan of every API
   endpoint signed in as a staging District Admin. Needs Docker and the staging admin's email,
   password and authenticator secret in `SCAN_EMAIL`, `SCAN_PASSWORD` and `SCAN_TOTP_SECRET`.
   The active scan creates junk records: use a staging copy you can throw away.
2. Dependency audits: `pip-audit --local` in `backend/`, `npm audit --omit=dev` in `frontend/`.
3. `bandit -q -r app` in `backend/`.

No high or medium finding may stay open. Record the results in the release's security review
(see `docs/security-review-phase5.md` for the go-live one).

A staging server reached by a name without a dot (for example `localhost`) needs a dotted name
instead, such as `sces.localhost` mapped to 127.0.0.1: Java clients like ZAP send no server name
for dotless hosts.

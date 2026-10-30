# Load test at design scale

Section 15 asks for list queries under 300 ms at design scale (500 schools, 10,000 teachers,
500 supervisors, 200,000 documents), realtime delivery under 2 seconds, and a 10-page scan
uploaded in under 30 seconds on 4G. Run before go-live and after any change to the server.

On a **staging** database, never production:

1. Fill it: from `backend/`, with the app's environment pointing at an empty, migrated
   staging database,

   ```bash
   PYTHONPATH=.:../e2e .venv/bin/python ../loadtest/seed_scale.py > seed.json
   ```

   About two minutes. The users in `seed.json` (from the browser-test seed) can sign in.
2. Start the API as in production (one process), with the rate limits raised for the test:
   `SCES_RATE_LIMIT_USER_PER_MINUTE=100000 SCES_RATE_LIMIT_IP_PER_MINUTE=100000`.
3. Run it:

   ```bash
   .venv/bin/python ../loadtest/run.py https://staging.example.org seed.json results.json
   ```

It prints, then writes to `results.json`:

- each list, search, dashboard and report a role uses: median and 95th percentile of 20 calls;
- 50 people at once for a minute: requests per second, errors, median and 95th percentile;
- 500 live connections (50 for the admin, 50 for the report's owner, 400 for other supervisors):
  how long an acknowledgement took to reach each one that may see it, and that none reached
  the others;
- 20 ten-page scans uploaded at once through the resumable upload.

The upload times are measured on the server's own network. On 4G, add the transfer time: a
ten-page scan of about 4 MB takes about 4 seconds at 8 Mbit/s upload.

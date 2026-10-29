# School Cluster Evaluation System

A district system to organize schools into clusters, assign supervisors to
visit them, collect evaluations through ministry report forms, and receive
scanned visit reports, which supervisors submit to the District Admins and
no other supervisor can see.

## Documents

- [Requirements v0.4](docs/requirements.md): the current specification,
  including district decisions, the scanned report vault, and open questions.
- [Delivery plan](docs/delivery-plan.md): the six delivery phases, with
  scope, exit criteria, blocking decisions, and current status.
- [Deployment guide](docs/deployment.md): installing on the district's server,
  mail setup, backups, and emergency access.
- [Requirements v0.2 (archived)](docs/archive/School_Cluster_Evaluation_System_Requirements_v0.2.docx)

## Layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI service, worker and CLI (Python 3.13, SQLAlchemy, Alembic, MySQL 8) |
| `frontend/` | React and TypeScript web app (Vite, TanStack Query, i18next), English and Arabic |
| `e2e/` | Browser smoke test, PWA check, and Phase 2 and 3 browser tests, run before each release |
| `deploy/` | Backup and restore scripts |
| `docker-compose.yml` | Production stack: MySQL, migrations, API, worker, ClamAV, Caddy web server |

## Development

You need Python 3.12 or later, Node 22, and a MySQL 8 server. A throwaway one:

```bash
docker run -d --name sces-mysql -e MYSQL_ROOT_PASSWORD=root -p 3306:3306 mysql:8.4 --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

Backend tests build their own database with the real migrations and connect as
a restricted user, as in production:

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]" ruff
```

```bash
cd backend && TEST_MYSQL_ROOT_URL=mysql+pymysql://root:root@127.0.0.1:3306 .venv/bin/pytest
```

Frontend checks:

```bash
cd frontend && npm ci && npm run typecheck && npm test
```

To run the app locally, set the `SCES_*` variables described in
`backend/app/config.py`. For local work, `SCES_MAIL_PROVIDER=console` logs mail
instead of sending it, `SCES_VIRUS_SCANNER=none` uses a test-only scanner, and
`SCES_STORAGE_PATH` points file storage at a local folder. Then:

```bash
cd backend && .venv/bin/python -m app.cli provision-database && .venv/bin/uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm run dev
```

The dev server on http://localhost:5173 proxies `/api` to port 8000.

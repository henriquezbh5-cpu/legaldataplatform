# Deploy to Railway

This deploys the **FastAPI ingestion console** so anyone with a URL can upload
a CSV, see the schema get fuzzy-matched, validated, normalized, and loaded
into a partitioned PostgreSQL 16 instance.

What gets deployed:
- 1x service: the FastAPI app (built from `Dockerfile.api`)
- 1x service: PostgreSQL 16 (Railway-managed)

What does **not** get deployed (intentional):
- Prefect / MinIO / Grafana — those are local-dev tools. The dashboard's
  topbar dots auto-hide them when unreachable.

---

## Prerequisites

- A GitHub account with this repo pushed (already done at
  `https://github.com/henriquezbh5-cpu/legaldataplatform`)
- A Railway account (free, sign in with GitHub at <https://railway.app>)

---

## Steps (~10 min)

### 1. Create the project

1. Go to <https://railway.app/new>
2. Click **"Deploy from GitHub repo"**
3. Authorize Railway to access your repos
4. Pick `legaldataplatform`
5. When asked which Dockerfile, choose `Dockerfile.api` (the
   `railway.toml` already declares this — should auto-detect)

### 2. Add PostgreSQL

1. Inside the project, click **"+ New"** → **"Database"** → **"Add PostgreSQL"**
2. Wait ~30s for it to provision
3. Railway auto-injects `DATABASE_URL` into your service. The `start.sh`
   script parses it into `POSTGRES_*` env vars on boot.

### 3. Set environment variables (optional)

The defaults work, but you can override on the API service:

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | Set to `production` if you want |
| `APP_LOG_LEVEL` | `INFO` | DEBUG / INFO / WARNING |

Railway auto-provides `PORT` and `DATABASE_URL`.

### 4. Generate a public domain

1. Open the API service → **Settings** → **Networking**
2. Click **"Generate Domain"**
3. You get a URL like `legaldataplatform-production-XXXX.up.railway.app`

### 5. First boot

The `start.sh` script will:
1. Parse `DATABASE_URL` → set `POSTGRES_*` env vars
2. Wait for PostgreSQL to be ready
3. Run `alembic upgrade head` (creates partitioned `legal_documents`,
   indexes, materialized views)
4. Auto-seed ~5,000 sample rows the first time (idempotent — won't
   duplicate on restart)
5. Launch `uvicorn` on `$PORT`

Watch the deploy logs. When you see `>>> [4/4] Launching uvicorn` you're live.

### 6. Test it

Open the URL. You should see the LegalDataPlatform Ingestion Console.
- Upload `data/samples/legal_documents.csv` (download from the GitHub repo
  if needed)
- Click "Run pipeline"
- Dashboard renders with charts, KPIs, partition inventory, etc.

---

## Costs

Railway free tier: **$5 of usage credit per month**. This setup typically
costs:
- API service: ~$0.50–1.50/month if always-on with low traffic
- PostgreSQL: ~$1.50–3/month

Total: comfortably inside the free credit for a portfolio demo. If you
exceed, you can pause the services or upgrade.

---

## Alternative: Render (if you prefer)

Render also works. The Dockerfile is the same. The differences:
- Render free tier puts the web to sleep after 15min of no traffic. First
  request after that takes ~30s to wake up.
- Render's free Postgres expires after 90 days; then it's $7/month.

Steps on Render:
1. New → Web Service → connect GitHub
2. Pick the repo, set Docker Path = `Dockerfile.api`
3. New → PostgreSQL (free)
4. In the web service env vars, add `DATABASE_URL` = the Render Postgres
   internal connection string

---

## Updating after the first deploy

Push to `main` on GitHub → Railway auto-deploys. The `start.sh` re-runs
migrations on every boot (idempotent), so schema changes apply automatically.

To force a re-seed (rare): connect to the DB via Railway's web console and
`TRUNCATE legal_documents` — next boot will re-seed.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Build fails on `pip install` | Some native deps need build tools; the multi-stage Dockerfile already handles this. Re-trigger the deploy. |
| `relation "legal_documents" does not exist` | Alembic didn't run. Check deploy logs. Most likely the DB env vars aren't set — verify `DATABASE_URL` is attached to the service. |
| Health dots in topbar all red | Expected on cloud — Prefect/MinIO/Grafana don't run there. The dots auto-hide their links. |
| Upload returns 500 | Check the `/runs/{id}/log` link in the response banner. |

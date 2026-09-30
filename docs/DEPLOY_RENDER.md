# Yuki deployment on Render

The checked-in `render.yaml` defines a Free Python API web service and a free
React/Vite static site. It does not create a Cron Job or trigger NOAA
acquisition. The Vercel files remain in place for reversibility; Render ignores
them.

## Runtime package and safety

Run `python scripts/audit_deployment.py` before a public push. It checks files
that `.gitignore` would let through without reading or printing `.secrets/`.
Also review staged files and Git history for secrets before pushing.

`scripts/build_runtime_bundle.py` copies only the V1 forecast-only source,
V1 historical analog source, V2 2024 forecast-only demo, and a validated
processed current run into `runtime/`. It also builds ten compressed,
lead-specific V2 analog indexes from **2021–23 training partitions only**.
The original 519 MiB V2 training partition directory stays local and ignored.
Each index retains the original double-precision feature/outcome values and
date order; it is not a retraining or 2025 final-test evaluation. The frozen
V1 and V2 model files remain under `models/` and are not rewritten.

The public bundle contains the state boundary dataset in
`frontend/public/data/`, with attribution in `BOUNDARY_SOURCE.txt`. The
bootstrap current run under `runtime/current/` is an immutable, dated
processed forecast, not live NOAA acquisition. The UI/API must continue to
display its run timestamp and source kind; do not label an old bootstrap as a
new live run.

Never commit `.secrets/`, CDS credentials, `.env` files, raw GFS/GEFS GRIB,
ERA5 downloads, training/evaluation data, logs, partial downloads, `.venv`,
`node_modules`, or frontend build outputs. The local research data is retained.

## Render services

| Service | Root | Build | Start / publish | Health |
| --- | --- | --- | --- | --- |
| API web | repository root | `pip install -r requirements-web.txt` | `python -m uvicorn forecast_bust.api.app:app --host 0.0.0.0 --port $PORT` | `/api/v2/health` |
| Site static | repository root | `cd frontend && npm ci && npm run build` | publish `frontend/dist` | n/a |

Render uses Python 3.13.15 and Node 24.21.0; `PYTHONPATH=src` is set for the
API. `requirements-web.txt` installs official CPU-only XGBoost 3.4.1, matching
the frozen model's version without CUDA/NCCL packages. The Blueprint selects
the Free 512 MB API plan and one worker. It retains only one full-grid V2
artifact and one analog lead index in RAM at a time. This affects cache
retention, not predictions or responses. V1 and V2 endpoints remain available.

Set these public origin values during Blueprint creation or after Render assigns
the final hostnames:

- API: `FORECAST_BUST_CORS_ORIGINS` = exact HTTPS static-site origin (for
  example `https://<site>.onrender.com`).
- Static site, at build time: `VITE_API_BASE_URL` = exact HTTPS API origin (for
  example `https://<api>.onrender.com`), without a trailing slash.

Never put credentials in Vite variables: they are embedded in public
JavaScript. Object-store variables are optional and are not needed for the
packaged current forecast.

The static site's `/* -> /index.html` rewrite keeps `/analysis`, `/risk`, and
`/explain` usable on direct visit. Local development still defaults to
`http://127.0.0.1:8000` when `VITE_API_BASE_URL` is unset.

## Current-run persistence and cold starts

The packaged 2026-09-29 12:00 UTC processed run is a dated forecast, not a
live NOAA download. No acquisition runs at API startup or page load. Render
Free's filesystem is ephemeral and its web service sleeps after 15 minutes
idle; the first request can take about a minute while it wakes. The existing
loading/error states remain visible and must not substitute fake forecasts.

For later current runs, run the existing `scripts/publish_v2_current.py`
workflow outside the web service with a private S3-compatible object store.
The publisher uploads validated immutable artifacts before advancing
`latest.json`; the API validates hashes before serving them. Set the API's
`FORECAST_BUST_OBJECT_BUCKET`, optional `FORECAST_BUST_OBJECT_ENDPOINT`, region,
and scoped read credentials only when that store is configured. The publisher
needs separately scoped write credentials. No paid Render Cron service is
included in this Blueprint.

## Local validation before push

From PowerShell in the project root:

```powershell
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe scripts/audit_deployment.py
.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
```

## GitHub → Render

1. Push the validated deployment commit to `main`. Connect the repository to
   a Render Blueprint using root `render.yaml`. Confirm it creates only the
   Free API and static site, with no paid service or Cron Job.
2. Enter or update the exact API/site origins above. If Render assigns
   different hostnames, correct both values and redeploy both services; the
   static-site API origin is baked in at build time.
3. Check the public API's `/api/v2/health`, `/api/v2/states`, current-run
   summary, state summary, Day 1 grid, and explainability endpoints. Then
   test all four screens and direct `/analysis`, `/risk`, `/explain` refreshes.

Frontend URL: pending Render deployment. Backend URL: pending Render deployment.
Do not mark the services live until public checks pass.

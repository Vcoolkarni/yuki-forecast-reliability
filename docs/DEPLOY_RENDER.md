# Yuki deployment preparation (not deployed)

The checked-in `render.yaml` describes a Render static site, a single-worker
FastAPI web service, and a once-daily forecast-publisher Cron Job. It does not
create services until you explicitly connect the repository in Render.

## Runtime package and safety

Run `python scripts/audit_deployment.py` before every first/public push. It
uses a temporary Git index and reports the files that `.gitignore` would let
through without reading or printing `.secrets/`. This checkout had no `.git`
directory during preparation, so no prior index/history exists here to audit.
If you later import a repository with existing commits, inspect its complete
history for secrets before making it public. Rotate/revoke any credential that
has ever been committed, remove it from Git history with a history-rewrite tool,
and coordinate the force-push with collaborators. Merely adding `.gitignore`
does not unpublish a committed secret.

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
| Publisher Cron | repository root | `pip install -r requirements-publisher.txt` | `python scripts/publish_v2_current.py` | n/a |

Render uses `.python-version` (Python 3.13.15) and the static build pins
`NODE_VERSION=24.21.0`, matching the clean local build. `PYTHONPATH=src` is set for
the Python services. Run one API worker unless memory/performance testing
justifies more: it loads the frozen model once per process and caches forecast
inference. Select an API/Publisher memory plan after reviewing Render cost and
testing full-grid responses; Render's default 512 MB may be tight, and the
Blueprint does not silently choose a larger paid plan. V1 endpoints, V2
endpoints, gzip responses, and the 2024 demo remain
available. The Render health check targets V2 readiness and its packaged
forecast; the original V1 `/health` route remains intact.

Set these environment-variable **names** in Render (never commit values):

- API: `FORECAST_BUST_CORS_ORIGINS` (exact HTTPS static-site origin, comma-separated
  for additional allowed origins), `FORECAST_BUST_OBJECT_BUCKET`,
  `FORECAST_BUST_OBJECT_ENDPOINT`, `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`.
- Static site (build time): `VITE_API_BASE_URL` (the public API HTTPS origin,
  without a trailing slash). This is required for Render's separate-origin
  static site and API; without it, production requests use the same origin.
- Publisher: the same object-store variables as the API. `PYTHONPATH` is
  configured in the Blueprint; Render supplies `PORT` to the web service.

`FORECAST_BUST_OBJECT_ENDPOINT` is the S3-compatible endpoint for the chosen
provider; for AWS S3, omit it. Use a private bucket. `FORECAST_BUST_OBJECT_PREFIX` is optional and
defaults to `yuki/v2/current`. Give the publisher write permission only to
that prefix and the API read permission only to that prefix if your provider
supports separate credentials. Never put object-store credentials in Vite:
static-site environment variables are embedded in public JavaScript.

The static site's `/* -> /index.html` rewrite keeps `/analysis`, `/risk`, and
`/explain` usable on direct visit. Local development still defaults to
`http://127.0.0.1:8000` when `VITE_API_BASE_URL` is unset.

## Processed-run persistence

Render web/cron filesystems are ephemeral, and [Render Cron Jobs cannot access
a web service's persistent disk](https://render.com/docs/cronjobs). Use one small
S3-compatible object bucket; no Postgres or Render disk is needed for this MVP.
The Cron Job downloads selective NOAA messages into its ephemeral cache,
validates Day 1–10 forecast features, runs frozen V2 inference, writes local
complete artifacts, then uploads `features.csv.gz`, `predictions.json.gz`, and
`manifest.json` under an immutable run ID. It writes remote `latest.json`
**last**, only after verifying artifact hashes. Failure leaves the prior
successful pointer unchanged. The API mirrors only the latest complete run
into its ephemeral local cache and verifies hashes before serving it. If the
bucket is unavailable, it keeps serving the last locally verified run or the
packaged bootstrap run. Opening the website never contacts NOAA.

The bucket prefix can later store ERA5 verification under a separate
`verification/` branch, keyed by run ID, without changing immutable original
forecast predictions. Do not inject ERA5 observations into operational
inference. Enable bucket versioning/retention according to the provider's
backup policy before relying on it as the sole archive.

The Blueprint's schedule `0 12 * * *` is **once daily at 12:00 UTC** (17:30
IST), not once per six-hour cycle. Discovery checks up to eight recent cycles
and publishes only a complete compatible GFS+GEFS initialization. The smoke
run downloaded 27,345,386 new NOAA payload bytes; future cost/time varies.
Do not increase frequency until observing several publisher durations,
availability delays, and hosting costs. Render Cron has no persistent cache,
but the selective byte-range logic and per-run 1 GiB transfer cap remain.

## Local validation before first push

From PowerShell in the project root:

```powershell
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe scripts/build_runtime_bundle.py
.venv\Scripts\python.exe scripts/audit_deployment.py
.venv\Scripts\python.exe -m pytest -q
```

For frontend validation, run `npm ci`, `npm test`, and a build with a temporary
non-secret API URL from `frontend/`. If Windows locks `node_modules`, use a
separate copied frontend directory and run the same commands there. Verify
the build embeds your configured HTTPS API origin and not a localhost origin.

## Manual GitHub → Render sequence

1. Review `scripts/audit_deployment.py` output and the public runtime data.
   This working directory currently has **no local Git history/index**.
2. Initialize Git locally if desired (`git init`), then inspect `git status
   --short --untracked-files=all` and `git add --dry-run .`. Verify `.secrets/`
   and all ignored research caches do not appear. If bringing older history,
   audit that history and rotate/remediate any exposed credentials first.
3. Only after review, create your GitHub repository, make a local commit, and
   push it yourself. No push or service creation is performed by this prep.
4. Create an S3-compatible bucket and scoped API/Publisher credentials. Choose
   your retention/versioning. Note its bucket name, endpoint, and region.
5. Connect the GitHub repo to a Render Blueprint using `render.yaml`. Review
   service plans/costs and enter the environment values. Once Render assigns
   service URLs, set `VITE_API_BASE_URL` to the API HTTPS origin and
   `FORECAST_BUST_CORS_ORIGINS` to the static-site HTTPS origin; rebuild both.
6. Verify `/api/v2/health` reports the frozen model, 36 state/UT polygons, the
   2024 historical demo, and the dated bootstrap current run. Open the static
   site and directly reload `/analysis`, `/risk`, and `/explain`.
7. Verify object-store access and manually run the publisher once in Render
   when ready. Check that a complete new run appears and that older successful
   runs remain intact. The daily schedule can then stay enabled.

No deployment, GitHub push, NOAA acquisition, retraining, or final-test
re-evaluation is part of these preparation steps.

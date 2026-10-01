# Archived Vercel deployment attempt (not production)

Yuki's active production deployment is [Render](DEPLOY_RENDER.md). This file is
retained solely as a record of the abandoned Vercel Services attempt; do not
follow the historical deployment steps below for the current website.

The former root `vercel.json` mapped Vite and FastAPI into Vercel Services, and
`.vercelignore` excluded local files from Vercel CLI uploads. Their associated
`tests/test_vercel_deployment.py` checked only that obsolete packaging. These
three files are unused by Render and the running Yuki application, so they were
removed from the active repository. The old `main.py` Vercel ASGI adapter is
also unused by Render, but remains untouched under the backend-code freeze.
Removing repository files **does not** disconnect a Vercel project's GitHub
integration. To stop future Vercel deployments, disconnect this repository in
that project's **Settings → Git → Connected Git Repository**.

## Historical configuration notes

The removed `vercel.json` used a Vercel **Services** configuration: `frontend`
was the public Vite site and `yuki-site` was the FastAPI service. The API was
reachable on the same deployment at `/api/*`; the V1 `/health` route and
FastAPI documentation routes also reach the backend. Frontend deep links
resolve to `index.html`. The backend uses the existing `requirements-web.txt`,
frozen models, and checked-in `runtime/` data through the lightweight
`main:app` entrypoint. The FastAPI function explicitly includes its model,
configuration, current/demo forecast, analog index, and India boundary files;
development-only files are excluded from that function bundle.

1. In Vercel's import screen, keep the project root at the repository root and
   select **Services** as the framework. Confirm the two services are `frontend`
   (Vite) and `yuki-site` (FastAPI). Do not set a separate root directory for
   the whole project.
2. Leave `VITE_API_BASE_URL` unset for this same-origin deployment. A custom
   value is only for separate-origin hosting. The local Vite dev server still
   defaults to `http://127.0.0.1:8000`.
3. Do not add credentials to Git; `.gitignore` and the former `.vercelignore` excluded
   local secrets from Git and CLI uploads. The bundled current forecast lets the site
   start without an object store. To serve newer published runs, configure the
   existing `FORECAST_BUST_OBJECT_BUCKET` and relevant S3-compatible endpoint,
   region, and credential variables in Vercel's environment settings. This
   configuration does not schedule or run the existing forecast publisher.
4. Review function bundle/build limits and usage before deploying. No paid
   compute, container, cron, or storage feature is configured in `vercel.json`.
   Verify `/api/v2/health`, `/`, and a direct refresh of `/analysis` after the
   first deployment. Local tests do not prove a remote Vercel build will pass.

No model training, weather acquisition, or 2025 final-test evaluation is part
of deployment.

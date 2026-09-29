# Local forecast API

The API loads the existing `ForecastInference` service and the local forecast CSV at
startup. GET endpoints do no fitting or acquisition. All operational fields retain the
project's original names, probabilities, calibration, saved decision threshold, confidence
and hotspot definitions. Pydantic defines the public output contract.

Install the declared API dependencies manually in the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install "fastapi>=0.115,<1" "uvicorn>=0.30,<1" "pydantic>=2.9,<3" "httpx>=0.27,<1"
```

Start from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn forecast_bust.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Interactive API documentation is available at `/docs`. Configuration is in
`config/api.yaml`; set `FORECAST_BUST_API_CONFIG` to use a different settings file.
Model/input/inference configuration paths are relative to the project root. CORS allows
only the configured local origins; wildcard origins and credentials are not enabled.

Routes:

- `/health`: readiness, model SHA-256, saved threshold, features, available initializations,
  and cache count. Returns HTTP 503 if the model/local source cannot be loaded.
- `/api/v1/forecast/{initialization}/summary`: overall and Day 1–10 summaries.
- `/api/v1/forecast/{initialization}/day/{lead_day}`: `records` for the lead (289 on the current grid).
- `/api/v1/forecast/{initialization}/day/{lead_day}/hotspots`: hotspot objects, possibly empty.
- `/api/v1/forecast/{initialization}/day/{lead_day}/highest-risk`: the complete highest-risk cell,
  including top contributions and explanation.
- `/api/v1/forecast/{initialization}/cell?latitude=22&longitude=78&lead_day=1`: a complete cell record.
- `/api/v1/forecast/{initialization}/timeline`: ten compact chart points under `days`.

Initialization accepts an ISO date (00 UTC) or ISO timestamp, normalized to UTC. Invalid
syntax and invalid leads return 422; unavailable initializations/grid coordinates return
404. Coordinate matching uses a numerical tolerance of 1e-8 degrees without nearest-cell
interpolation. Pass grid coordinates returned by the day endpoint.

Each initialization is inferred once while present in the bounded in-memory LRU cache.
The cache defaults to four initializations. A lock serializes cache misses to prevent
duplicate concurrent inference. Each worker has its own cache; restart the API to load a
changed model or forecast source. There is no persistent cache mutation or invalidation
of GFS/ERA5 caches. Model-derived confidence and raw TreeSHAP attributions retain the
limitations documented in `docs/inference.md`.

Run tests after installing API dependencies:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

HTTP tests are skipped explicitly when API dependencies are unavailable. Repository/cache
tests do not require FastAPI and remain runnable with the existing ML environment.

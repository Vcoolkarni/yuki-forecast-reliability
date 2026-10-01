# Archived Phase 1 / V1 project notes

This document preserves earlier development notes as historical provenance. Some
descriptions and commands below predate the frozen V2 Yuki release; see the
[current root README](../README.md) and [Render deployment guide](DEPLOY_RENDER.md)
for the active application.

# SIH26079 — Forecast Bust Detection (Phase 1)

For the active Yuki V2 production bundle, see the
[Render checklist](DEPLOY_RENDER.md). The
[archived Vercel notes](DEPLOY_VERCEL.md) describe an abandoned attempt.
Neither document deploys, acquires weather data, or retrains by itself.

Working Python foundation for predicting where and at which lead day a deterministic
medium-range rainfall forecast is likely to have a large error. This phase deliberately
does **not** include a frontend and never substitutes synthetic/random weather data when
a source is unavailable.

## MVP data decision

Use one 00 UTC GFS initialization per day, Day 1–Day 10 precipitation, over the small
4° × 4° central-India box in `config/default.yaml`, verified against hourly ERA5 total
precipitation accumulated to the exact same precipitation window. Start with 7 dates to
validate plumbing, then expand to at least 1–3 monsoon seasons for meaningful training.

Why this is the smallest defensible proof:

- NOAA GFS is public and needs no AWS account. The current AWS public bucket is most
  convenient but only has a trailing window; NCEI provides the longer archive.
- ERA5 is an hourly, 0.25° reference suitable for the GFS 0.25° grid after explicit
  remapping. It requires a free Copernicus Climate Data Store (CDS) account, acceptance
  of the dataset licence, and an API token.
- Forecast and reference precipitation must cover identical accumulation periods.
  A forecast step must never be joined directly to an arbitrary ERA5 hour.

The repository writes a precise ERA5 request plan but does not submit it automatically.
The remaining GFS downloader will be finalized against the chosen archive dates; this
avoids silently mixing operational model versions or downloading global GRIB files.

## Structure

```text
config/                  YAML runtime configuration
data/raw/                immutable source files (gitignored)
data/interim/            request manifests and normalized source data
data/processed/          matched, labeled ML table
models/                  serialized trained model
reports/                 metrics, probabilities, and SHAP plot
src/forecast_bust/       acquisition, I/O, matching, labeling, features, training
tests/                   unit tests
```

## Dataset contract

The processed table must contain:

| Column | Meaning |
|---|---|
| `initialization_time` | UTC model cycle |
| `valid_time` | UTC end of the verified accumulation window |
| `latitude`, `longitude` | matched/regridded grid-cell centre |
| `lead_day` | integer 1–10 |
| `forecast_precipitation` | GFS accumulated precipitation, mm |
| `reference_precipitation` | ERA5 precipitation over the same window, mm |
| `forecast_error` | forecast minus reference, mm |
| `absolute_error` | absolute forecast error, mm |
| `is_bust` | configurable binary label |

Extra predictor columns can be added without changing this core contract. The initial
label is `absolute_error >= bust_threshold_mm`; the registry in `labeling.py` makes it
replaceable with percentile-, region-, or event-aware definitions later.

## Setup and commands

PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
pip install -e .
python -m forecast_bust.cli --config config/default.yaml init
python -m forecast_bust.cli --config config/default.yaml plan-era5
pytest -q
```

`plan-era5` creates `data/interim/era5_request.json` and downloads nothing.

For the minimal real-data smoke test, `config/smoke.yaml` uses one GFS 00 UTC
initialization at +24 h and a 4° × 4° box. The acquisition code reads the public GFS
`.idx` inventory and requests only the selected `APCP` byte range; it refuses to save a
full global GRIB if the server ignores that range.

### Obtain the real data

1. Create a free CDS account at <https://cds.climate.copernicus.eu/>.
2. Accept the licence on the **ERA5 hourly data on single levels** dataset page.
3. Copy the personal access token into the standard CDS API configuration described by
   the CDS user guide. Never commit that token; `.cdsapirc` and `.env` are ignored.
4. Keep the configured box/date range small. Submit the generated request using the
   official `cdsapi` client only after reviewing its area, dates, and variable.
5. Obtain GFS forecast GRIB2 files from NOAA's public AWS bucket for recent dates or
   the NCEI archive for older dates. Select only `APCP` records and required lead steps
   using each GRIB2 `.idx` inventory/byte ranges, then spatially crop and normalize.

Acquisition stops explicitly if credentials/licence acceptance are unavailable. GFS
selection can proceed independently because the NOAA source is public; ERA5 still
requires the account owner to accept its licence in the CDS web interface.

The smoke preprocessing uses the GFS `0-1 day acc fcst` precipitation record and sums
24 ERA5 hourly precipitation fields over the identical `(initialization, valid_time]`
window. ERA5 metres are explicitly converted to millimetres. A missing hour or unknown
unit raises an error.

### Build a matched dataset

After source normalization, provide CSVs with these columns:

- Forecast: `initialization_time,valid_time,latitude,longitude,lead_day,forecast_precipitation`
- Reference: `valid_time,latitude,longitude,reference_precipitation`

The grids must already be identical (explicit conservative/bilinear regridding belongs
in preprocessing, not in the matcher):

```powershell
python -m forecast_bust.cli --config config/default.yaml match `
  --forecast data/interim/gfs_precip.csv `
  --reference data/interim/era5_precip.csv `
  --output data/processed/dataset.csv
```

The command refuses unmatched rows and validates the schema.

### Train, evaluate, and explain

```powershell
python -m forecast_bust.cli --config config/default.yaml train `
  --dataset data/processed/dataset.csv
```

Outputs:

- `models/xgboost.joblib`
- `reports/metrics.json` — precision, recall, F1, ROC-AUC, confusion matrix
- `reports/predictions.csv` — `bust_probability` and `forecast_confidence`
- `reports/shap_summary.png` — global feature attribution

The split is chronological by initialization time to avoid leaking grid cells from one
forecast cycle into both train and test. SHAP is explanatory, not causal; meteorological
reason text should later combine SHAP values with named physical predictors such as
moisture, pressure tendency, wind/shear, and ensemble spread.

### Extended Phase 2 predictors

`config/phase2.yaml` now declares each GFS predictor, its GRIB inventory selector,
cache suffix, output column, and accumulation behavior. The dataset builder supports:

- daily precipitation derived from cumulative `APCP` fields;
- 2 m temperature and relative humidity;
- mean sea-level pressure;
- 10 m U and V wind components;
- derived 10 m wind speed;
- precipitation spatial-gradient magnitude in mm per degree.

The cache filenames include initialization, lead, and predictor, so existing precipitation
messages remain reusable. Model features no longer include `day_of_year`.

## Scientific limitations of the first baseline

- A 7-day slice proves execution only; it cannot train a credible operational model.
- ERA5 is a model-based reanalysis, not rain-gauge truth, and has precipitation biases.
- Grid remapping and accumulation-window semantics must be recorded in provenance.
- Random row splitting is invalid here; independent initialization times are required.
- The absolute-error threshold is an MVP rule and should be calibrated by region/season.

## Official access references

- NOAA GFS public AWS dataset: <https://registry.opendata.aws/noaa-gfs-bdp-pds/>
- NOAA/NCEI GFS archive and access methods: <https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast>
- ERA5 hourly single levels: <https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels>

## Yuki dashboard (local product prototype)

V2 India/state-oriented work is isolated and untrained; see
[Phase A architecture and offline estimator](docs/v2_phase_a.md). The current
Central India V1 application remains the operational default.

The `frontend/` React/TypeScript/Vite application uses the supplied Yuki logo and
background. Its four routes are Overview (`/`), Forecast Analysis (`/analysis`),
Risk & Hotspots (`/risk`), and Why This Forecast? (`/explain`). All displayed
forecast values come from the local FastAPI service; no demo data is substituted
when an endpoint fails. The initialization selector contains only runs reported by
`/health`. The default is the latest available local run.

In one PowerShell terminal, from the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn forecast_bust.api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. Set `VITE_API_BASE_URL` via `frontend/.env.local`
when the API is on a different address; `frontend/.env.example` shows the value.
The API CORS origins live in `config/api.yaml`. The map overlays use the local
17×17 GFS forecast grid. OpenStreetMap basemap tiles need internet access; forecast
cells and their values still originate from the local API.

The dashboard adds three API-backed views without retraining the model:

- `GET /api/v1/compare?current_initialization=...&previous_initialization=...&lead_day=...`
  compares matched grid cells at the same **lead day**. Because the runs have
  different initialization dates, their valid dates also differ; the change is
  a run-to-run risk signal, not a measured error or a same-valid-time revision.
  New/resolved hotspot regions are counted using non-overlapping hotspot
  bounding boxes, so they are a coarse spatial escalation indicator.
- `GET /api/v1/forecast/{initialization}/cell/analogs?latitude=...&longitude=...&lead_day=...`
  ranks forecast-only, standardized model feature vectors from the existing
  historical dataset. It excludes the selected initialization, returns at most
  one analog per historical run, then attaches ERA5 reanalysis outcomes **after**
  ranking. Historical `is_bust` follows the stored fixed 20 mm absolute-error
  label; this may differ from the deployed model's trained label definition.
  Similarity and analog outcomes are descriptive, not forecast probabilities.
- `GET /api/v1/forecast/{initialization}/day/{lead_day}/brief` generates offline,
  deterministic text from cached inference predictions, hotspots, and TreeSHAP
  feature names. It does not call an LLM or claim physical causality.

Forecast Analysis also uses the compact
`GET /api/v1/forecast/{initialization}/variables/trend?field=...` endpoint to
avoid transferring ten complete 289-cell daily payloads for a simple trend.
The API keeps inference artifacts in its existing per-worker LRU cache and does
not access ERA5 during operational prediction. The analog endpoint is the only
product endpoint that reads historical reference outcomes.

### Map display and interaction

The map's smooth 512-pixel raster is **display-only** bilinear sampling of each
complete, regular 17×17 source grid. It adds no forecast cells or information:
all hover/click values, summaries, hotspot membership, and model calculations
remain tied to the original 289 API records per day. The raster and dashed
outline are clipped to the configured 20–24°N, 76–80°E source-coordinate
domain. Hotspot fills and contiguous outlines use the API's actual
member-cell coordinates, not interpolated risk or bounding-box membership.
Selecting a cell persists across the four routes for the chosen initialization
and lead day; the highest-risk action opens its model-contribution explanation.
Run comparison uses the same display-only method, with a zero-centered diverging
palette for probability changes in percentage points. Rapid day/run/layer changes
discard stale responses.

The bundled state boundary/label asset is
`frontend/public/data/central-india-states.geojson`. It derives from the
[geoBoundaries India ADM1 gbOpen release](https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/)
(underlying DataMeet India/Election Commission material; CC BY 2.5 India).
See `frontend/public/data/BOUNDARY_SOURCE.txt` for the exact release, checksum,
and transformation. The source represents 2011 administrative geography; map
lines are context, not a claim about present legal boundaries. To regenerate
the local asset from that pinned source, use `scripts/prepare_ui_boundaries.py`;
the running dashboard does not fetch boundary data from an external service.

The read-only product-data check uses existing local model/data caches:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\check_product_data.py
```

To verify locally:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm test
npm run build
```

### V2 website integration and separately published current forecast

The approved Yuki screens now call the separate `/api/v2` backend. `/api/v1`
and the default V1 model remain available. V2 loads only the frozen classifier,
Platt calibrator, expected-absolute-error regressor, feature schema, and stored
decision threshold in `models/v2/recommended_0p50/`; inference never loads ERA5
or ground-truth labels. Its confidence display is `100 × (1 − calibrated bust
probability)`, a model-derived score rather than a probability of meteorological
correctness. TreeSHAP contributions are model attributions, not causal claims.

The retained sample feed contains two **historical 2024** forecast-only runs
(26 and 29 September) extracted from already-cached validation forecasts. It
contains no ERA5/reference/error/bust columns. It is explicitly marked
`historical_demo` in `/api/v2/health` and in the Yuki header; it must never be
presented as a current forecast. To regenerate it from local caches only:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\prepare_v2_demo.py
```

To discover the newest *complete* NOAA GFS+GEFS 0.5° cycle and publish one
forecast-only Day 1–10 run, run this separately from the API (never on a page
request):

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\publish_v2_current.py
```

The publisher checks all 160 required `.idx` messages, falls back from an
incomplete cycle, acquires only selected GRIB byte ranges with validated
atomic caches and a per-run byte cap, then checks the frozen feature schema,
units, full grid and every lead. It uses no ERA5. Outputs are isolated under
`data/processed/v2/current/runs/<YYYYMMDDHH>/`; `latest.json` changes only
after both the forecast-only features and frozen predictions are complete.
Published manifests and prediction hashes retain the original prediction for
future verification without changing frozen training/test artifacts. Re-running
the command reuses validated caches and an already published run. Restart the
backend after a new publish; the newest successfully processed current run is
primary, while the two 2024 demos remain selectable. Failed acquisitions leave
the previous successful current pointer untouched.

For a separately acquired current forecast-only CSV with the exact frozen V2
features and complete Day 1–10 grid, set `FORECAST_BUST_V2_FORECAST_PATH` to its
absolute path before starting the API. The API rejects target/reference columns
and labels this input `forecast_only_feed`; it does not infer that a feed is live
solely from its filename or timestamp.

Start the API and existing frontend with the commands above. The new routes
include `/api/v2/health`, `/api/v2/states`, `/api/v2/runs/{initialization}/metadata`, `/api/v2/forecast/{initialization}`
`/summary`, `/day/{lead_day}`, `/day/{lead_day}/hotspots`,
`/day/{lead_day}/highest-risk`, `/cell`, `/cell/explainability`, `/timeline`,
`/state/{state}/day/{lead_day}`, `/state/{state}/summary`,
`/state/{state}/timeline`, `/state/{state}/day/{lead_day}/brief`,
`/day/{lead_day}/expected-error`, `/day/{lead_day}/gefs-uncertainty`,
`/day/{lead_day}/escalation`, `/cell/analogs`, and `/api/v2/compare`.
The India ADM1 boundary asset contains all 36 state/UT polygons from the pinned
geoBoundaries release. At the 0.5° model resolution, 31 units have one or more
co-located grid centers; the other five return a clear no-coverage response.
State summaries aggregate those underlying cells; they do not assert one
uniform forecast for a whole state. GEFS spread is the published **final six-hour
interval** spread, not a constructed daily ensemble spread.

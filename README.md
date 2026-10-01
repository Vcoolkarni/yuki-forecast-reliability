# Yuki ☁️

**AI/ML-Based Forecast Bust Detection for Medium-Range Weather Forecasts**

*How much should we trust the forecast we already have?*

## Overview

Yuki does not predict the weather again. It analyzes existing medium-range
numerical weather forecasts and estimates **where and when those forecasts may
have unusually large errors**. The result is a forecast-reliability layer for
India, shown by grid cell, state/Union Territory, and lead day.

## Live demo

**LIVE WEB APPLICATION:** [Open Yuki](https://yuki-site-caq0.onrender.com)

## The problem

A *forecast bust* is a forecast error large enough to matter for decisions.
Rapidly changing weather can make a plausible-looking Day 1–10 forecast less
reliable in particular places. A single national accuracy number cannot show
those local, lead-dependent risks.

## What Yuki does

- **Forecast confidence:** a 0–100 model-derived score, calculated as
  `100 × (1 − bust probability)`.
- **Bust probability and classification:** calibrated risk estimates and a
  validation-selected decision threshold.
- **Expected error:** predicted absolute precipitation error in millimetres.
- **Risk and hotspots:** contiguous groups of elevated-risk forecast grid cells.
- **Day 1–10 and state-wise analysis:** cell-level maps, state summaries, and
  confidence timelines. State values aggregate covered cells; they are not one
  uniform forecast for an entire state.
- **Explainability:** forecast-feature contributions that influenced a model
  prediction.
- **Forecast run comparison and early-warning escalation:** changes in
  predicted risk between comparable forecast runs.
- **Historical Analog Explorer:** similar 2021–23 training forecasts with
  their later reference outcomes, clearly separated from current inference.
- **Latest NOAA forecast analysis:** a separate, validated publishing workflow
  can apply the frozen models to a newly acquired forecast without retraining.

At the current 0.5° resolution, 31 of 36 state/UT boundaries contain a model
grid centre. Yuki reports explicit no-coverage for the other five; it does not
invent state forecasts.

## How it works

```text
NOAA GFS + GEFS forecasts
          ↓
Feature engineering and forecast-grid matching
          ↓
Frozen XGBoost classifier + expected-error regressor
          ↓
Bust probability + expected absolute error
          ↓
Confidence, hotspots and model contributions
          ↓
FastAPI → Yuki React dashboard
```

Historical [Copernicus ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
reanalysis supplies the **reference** used to construct historical precipitation
errors and training labels. Operational inference uses forecast features only;
it does not require ERA5 or future observations.

## Dataset and evaluation

| Partition | Forecast initialization period |
| --- | --- |
| Training | 2021–2023 |
| Validation | 2024 |
| Untouched final test | 2025 |

The V2 historical dataset contains **175 initialization dates** and
**6,725,250 grid-cell/lead samples** on an India-wide **0.5° forecast grid**
for **Day 1–10**. Grid cells and lead days from one initialization are spatially
and temporally correlated. Millions of rows are **not** millions of independent
weather events. The split is chronological by initialization, not random by
grid cell.

### Frozen V2 model performance

The following are the recorded, untouched 2025 final-test results—not metrics
recomputed for this README:

| Bust classifier | Score |
| --- | ---: |
| ROC-AUC | 0.901 |
| PR-AUC | 0.597 |
| Precision | 0.503 |
| Recall | 0.602 |
| F1 | 0.548 |
| Brier score | 0.058 |

The expected-absolute-error regressor recorded **MAE 3.76 mm** and
**RMSE 8.08 mm**. The frozen bust-classification threshold is approximately
**0.262539**. ROC-AUC measures ranking ability; it is not raw accuracy.

## Current forecast support

Yuki can process a latest NOAA GFS/GEFS forecast with the frozen V2 models,
without retraining. The forecast currently packaged with this repository was
initialized **2026-09-29 12:00 UTC** and contains **3,843 grid cells ×
Day 1–10 = 38,430 predictions**. Its timestamp is displayed in the product;
it must not be mistaken for a continuously updating live feed.

These current-run predictions have **not yet been verified** against later
ERA5 reanalysis. Two separately labelled September 2024 historical-demo runs
are also available in the application.

## Tech stack

| Layer | Tools |
| --- | --- |
| AI and backend | Python, XGBoost, FastAPI, model contributions/SHAP, pandas, xarray |
| Frontend | React, TypeScript, Vite |
| Forecast and reference data | NOAA GFS, NOAA GEFS, Copernicus ERA5 |
| Production hosting | Render |

## Project structure

```text
config/                 Forecast, inference and API configuration
src/forecast_bust/      Acquisition, features, training and API modules
frontend/               React/TypeScript dashboard and local boundary asset
models/v2/              Frozen V2 classifier, calibrator and error regressor
runtime/                Packaged forecast-only runs and training-only analog index
data/                   Local raw, intermediate and processed research data
scripts/                Acquisition, publishing, packaging and validation tools
tests/                  Backend and scientific regression tests
docs/                   API, scientific provenance and Render deployment notes
reports/                Local evaluation outputs (not required by the live API)
```

Raw weather downloads, local processed research tables, credentials, and
environment files are not committed. Packaged `runtime/` artifacts are
distinct from those local research caches.

## Running locally

These commands serve the existing packaged forecast. They do **not** download
weather data or retrain a model.

### Windows PowerShell

```powershell
cd C:\SIH26079-ForecastBust
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn forecast_bust.api.app:app --reload --port 8000
```

In a second terminal:

```powershell
cd C:\SIH26079-ForecastBust\frontend
npm ci
npm run dev
```

### Linux/macOS

```bash
python3.13 -m venv .venv
./.venv/bin/python -m pip install -r requirements-web.txt
PYTHONPATH=src ./.venv/bin/python -m uvicorn forecast_bust.api.app:app --reload --port 8000
```

In a second terminal, run `cd frontend && npm ci && npm run dev`.
Open the frontend at <http://127.0.0.1:5173>; the API is at
<http://127.0.0.1:8000>. See [API documentation](docs/api.md) and the
[Render deployment guide](docs/DEPLOY_RENDER.md) for more detail.

## Scientific notes

- ERA5 is a historical model-based reanalysis/reference, **not literal ground
  truth**.
- Forecast confidence is a deterministic transformation of model bust
  probability, **not** a calibrated meteorological probability that a
  forecast is correct.
- SHAP/model contributions describe factors influencing the model output;
  they do **not** establish physical causality.
- Yuki assesses existing numerical forecasts; it does not replace GFS, GEFS,
  forecasters, or other NWP systems.
- A current forecast needs later reference-data verification before its actual
  error can be known. Predicted zero or near-zero risk is a valid model output,
  not a guarantee.

## Deployment

The production frontend and FastAPI backend run on **Render**:
[yuki-site-caq0.onrender.com](https://yuki-site-caq0.onrender.com).
The [Render deployment notes](docs/DEPLOY_RENDER.md) describe the packaged
artifacts, environment settings, and cold-start behavior. Forecast publication
is separate from website deployment.

## Smart India Hackathon

Built for **Smart India Hackathon 2026**, problem statement **SIH26079:
AI-Based Forecast Bust Detection for Medium-Range Weather Forecasts**.

## Data sources and references

- [NOAA GFS on NOMADS](https://www.nco.ncep.noaa.gov/pmb/products/gfs/nomads/)
- [NOAA GEFS product inventory](https://www.nco.ncep.noaa.gov/pmb/products/gens/)
- [Copernicus ERA5 hourly single-level reanalysis](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
- [XGBoost documentation](https://xgboost.readthedocs.io/en/stable/)
- [SHAP documentation](https://shap.readthedocs.io/en/latest/)

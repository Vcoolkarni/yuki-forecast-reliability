# Phase 2 inference output

`ForecastInference` is a reusable Python service. A later API can load the trusted
joblib bundle once and call `predict_initialization(forecast_dataframe)` directly.
There are no downloads, ERA5 dependencies, label fitting, calibration fitting, or
training operations in this path. Training code, datasets, and artifacts are unchanged.

The input is one initialization with Day 1–10 on a shared complete regular grid. The
17×17 project grid produces 2,890 records. The service also accepts other complete
regular grids. It uses the saved feature order and the existing `build_features`
and, when needed, `add_derived_meteorological_features` functions. Project field
names are retained: for example `forecast_temperature_2m`,
`forecast_wind_speed_10m`, and `precipitation_gradient_mm_per_degree`.

Missing leads/cells, duplicate cells, inconsistent valid times, invalid coordinates,
nonfinite predictors, and target/reference columns fail explicitly. The allowed model
features are checked against the current preprocessing contract. Inference inputs must
not contain `reference_precipitation`, `forecast_error`, `absolute_error`, or `is_bust`.
Use `data/interim/gfs_phase2_forecast.csv`, not the labeled processed dataset.

Probabilities follow Phase 2 exactly: XGBoost `predict_proba`, clipping to `[1e-6,
1-1e-6]` for logits, then the saved Platt calibrator's `predict_proba`. Classification
uses `probability >= bundle['decision_threshold']`. An old bundle missing a stored
threshold is rejected; there is no 0.5 fallback.

Confidence is `100 * (1 - calibrated_bust_probability)`. It is a model-derived score,
not a calibrated meteorological probability that the forecast is correct. Defaults in
`config/inference.yaml`: High ≥80, Moderate ≥50 and <80, Low <50. These display
categories do not change the model or its saved decision threshold.

Hotspots use flood-fill connected components of cells with calibrated probability
at least the configured risk threshold. The default risk threshold is the saved
classification threshold. Four-neighbor connectivity and at least two cells are the
defaults; eight-neighbor adjacency is optional. Centroids are arithmetic cell-centre
means; bounding boxes describe cell centres, not polygons or cell edges. IDs are
deterministic within an initialization. No reference information is used.

TreeSHAP uses native XGBoost `pred_contribs=True`, matching the existing training
fallback. Each prediction contains the top absolute feature contributions, their
feature values/directions, the base value, and a deterministic explanation. Contributions
are in raw XGBoost log-odds before Platt calibration. They explain the model score,
not probability percentage points and not meteorological causation. Feature values
include all actual model inputs, so location/calendar/lead may appear among the top
factors. Do not convert these into asserted weather causes.

The strict JSON artifact contains `records`, `hotspots`, `lead_day_summaries`,
`initialization_summary`, the saved decision threshold, model SHA-256, and metadata
including units and configuration. Day and overall summaries include mean/maximum
probability, mean confidence, percentage predicted bust, hotspot count, and highest-risk
location (ties resolve by sorted lead/latitude/longitude). Overall averages weight each
grid-cell/lead prediction equally.

From the project root in PowerShell:

```powershell
$env:PYTHONPATH = Join-Path $PWD "src"; .\.venv\Scripts\python.exe scripts\infer_phase2.py --initialization 2026-09-12 --output reports\phase2_inference_20260912.json
```

This reads only the existing forecast CSV and saved model, and writes the requested
JSON artifact. Alternative local forecast/model/config paths are CLI options.

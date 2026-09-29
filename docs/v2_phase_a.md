# Yuki V2 Phase A — architecture and acquisition plan

> Historical planning note: the cumulative-APCP assumption below was superseded
> by the verified six-hour interval logic in `docs/v2_acquisition_profiles.md`.
> Use that document and the current V2 code for any future acquisition.

V2 is a separate, untrained planning path. The operational V1 model, API,
Central India data, and four-page UI remain unchanged. Running the estimator
reads local cache metadata only: it makes **zero** NOAA/CDS requests, writes
no data, and does not fit a model.

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\estimate_v2.py --config config\v2.yaml
```

The proposed pilot is four July–September monsoons (2022–2025), one 00 UTC
initialization every seven days *within each year's season*, 56 dates, all
Day 1–10 leads. Use 2022–2023 for training, 2024 for validation, and 2025
as a frozen test period. There is a 10-day minimum initialization/verification
embargo; no claim is made that dates within each season are independent weather
events. Historical source retention and variable consistency across years must
be checked with a few small `.idx` probes **before** approving a bulk run.
Phase A made *index-only* spot checks: both GFS and GEFS f024 inventories returned
HTTP 200 for 2022-07-01, 2023-07-01, and 2025-09-30; GFS f240 contained each
new proposed selector once on the first and last dates; GEFS f006/f024/f240
showed 0–6, 18–24, and 234–240 hour APCP intervals respectively on a
2026 sample. These tiny metadata checks did not download any GRIB field and
do not establish completeness for all 56 initialization dates.

The India planning envelope is 6–37°N, 68–98°E at 0.25°. This is only a
configurable acquisition/model design, not existing India-wide prediction
coverage. The local boundary asset currently includes six Central India states
only. `v2.geography` tests polygon membership of original grid-cell centers and
labels summaries `partial_grid_domain` when state geometry extends outside a
declared domain. No state selector is exposed in the V1 dashboard: presenting
partial Central India predictions as whole-state results would be misleading.
The full rectangular envelope contains 15,125 grid centers per lead and would
produce about 8.47 million forecast rows across the proposed 56 dates and ten
leads; the V2 grid validator rejects missing/duplicate centers.

## Forecast-time fields

NOAA GFS `pgrb2.0p25` messages are selected via `.idx` byte offsets. The
instantaneous fields are sampled at each Day N valid time; daily precipitation
is the difference of consecutive *verified cumulative* APCP messages. The
inventory selector must resolve exactly once, or acquisition stops.

| Field | GFS GRIB parameter/level | Unit | Transformation and interpretation |
| --- | --- | --- | --- |
| Daily precipitation | APCP surface, cumulative 0–N days | mm/24 h | Consecutive cumulative difference; predicted rainfall amount |
| 2 m temperature | TMP 2 m above ground | K | Instantaneous; near-surface thermal state |
| 2 m relative humidity | RH 2 m above ground | % | Instantaneous; near-surface moisture |
| Mean sea-level pressure | PRMSL mean sea level | Pa | Instantaneous; broad pressure pattern |
| 10 m U/V | UGRD/VGRD 10 m above ground | m/s | Instantaneous wind components; speed = hypot(U,V) |
| Precipitation gradient | Derived from daily GFS APCP | mm/degree | Gridwise gradient magnitude; rainfall contrast |
| CAPE | CAPE surface | J/kg | Instantaneous; potential convective instability, **not** a storm label |
| Precipitable water | PWAT entire atmospheric column | kg/m² | Instantaneous; column moisture supply |
| 500 hPa height | HGT 500 mb | gpm | Instantaneous; mid-level circulation pattern |
| 700 hPa vertical velocity | VVEL 700 mb | Pa/s | Instantaneous pressure-coordinate motion; sign matters |
| 850 hPa U/V | UGRD/VGRD 850 mb | m/s | Instantaneous lower-tropospheric flow/transport |
| 200 hPa U/V | UGRD/VGRD 200 mb | m/s | Instantaneous upper-level flow |

The selection is limited to physically interpretable rainfall, moisture,
instability, and circulation context. Derived relative vorticity and named
cyclone/depression/monsoon-state labels are **not** implemented without spatial
quality control or verified event catalogues. More atmospheric levels are not
requested indiscriminately. NOAA's [GFS inventory](https://www.nco.ncep.noaa.gov/pmb/products/gfs/)
documents the parameter/level combinations.

## GEFS and reference data

The optional GEFS plan uses 31 control/perturbed members (`c00`, `p01`–`p30`)
from `pgrb2sp25` at 0.25°. For each member and day, the planner requests four
6-hour APCP intervals. The downloader checks the actual inventory accumulation
start/end, then the aggregator requires all four exact intervals before summing.
It refuses absent members, mismatched grids, non-finite values, and duplicate
keys. A source that does not provide these exact intervals will require a
revised, explicitly reviewed plan—not silently substituted precipitation.
The resulting forecast-time predictors are member mean, population standard
deviation, min/max, P10/P90, range, fractions at or above 10/20/50 mm, and
GFS-minus-ensemble-mean. The coefficient of variation is undefined when mean
rainfall is at or below 1 mm and remains missing, not zero-filled. GEFS spread
means member disagreement, **not** known forecast error. NOAA's
[GEFS product inventory](https://www.nco.ncep.noaa.gov/pmb/products/gens/)
and [public AWS dataset](https://registry.opendata.aws/noaa-gefs/) document
the source structure; historical availability for every selected date is not
guaranteed by those pages.

The only V2 ERA5 request variable is `total_precipitation` from hourly
single-level reanalysis, in monthly bounded requests. Match the exact 24
hourly endpoints `(initialization + Day N-1, initialization + Day N]`, convert
metres to mm, and verify against the exact GFS grid/time. Missing hours or
reference cells fail the build. ERA5 is a **reanalysis reference**, not
rain-gauge ground truth. Monthly caches are never overwritten merely because
some coverage is missing; missing-date request plans receive distinct names.

## Dataset and model contracts

One row is one `(initialization_time, lead_day, latitude, longitude)` with
`valid_time`, deterministic forecast fields, optional complete GEFS summary
fields, ERA5 precipitation, signed forecast error, absolute error, and
`target_absolute_error_mm`. Duplicate keys, non-finite essential predictors,
and non-exact reference matches fail validation. The regression target is the
historical **absolute precipitation error**; no regression model or uncertainty
interval has been fit. Percentile bust labels remain training-period-derived,
not chosen from validation/test. V2 manifests record schema/config/file hashes,
initialization dates, leads, row count, coverage, and source provenance.

The temporal split module puts complete initialization dates in chronological
train/validation/test blocks, checks a Day-10 embargo and non-overlapping
verification windows. Phase C must choose label thresholds, calibration,
hyperparameters, and pooled-vs-lead-specific strategy using train/validation
only. Prepared metrics include precision, recall, F1, ROC-AUC, PR-AUC, Brier,
confusion matrix, and expected-error MAE/RMSE/median absolute error, including
per-lead reporting. No test-set selection is coded.

`config/model_registry.yaml` records V1 as ready and V2 as planned. V2 cannot
be resolved for inference until it has been trained and explicitly marked
ready. V1 remains the default rollback and its artifact is never rewritten.

## Cost and safety boundary

The current offline estimate is 7,840 GFS messages, 69,440 GEFS interval/member
messages, 16 ERA5 months, 77,296 uncached data requests, an additional 77,280
small `.idx` lookups (roughly 154,576 network operations before retries/CDS
polling), and about 52.6 GiB.
The estimate uses the median size of existing GFS GRIB messages (about 0.807
MiB) plus **assumed**, unmeasured GEFS (0.65 MiB/message) and ERA5 (150
MiB/month) sizes. It excludes `.idx` response bytes, protocol overhead,
request retries, and extracted/intermediate dataset storage. India-wide
hourly ERA5 NetCDF may be much larger; actual cost must be re-estimated from
a small approved source probe. The count is a **plan**, not proof that all
historical objects exist. No bulk acquisition is started by Phase A.
Six sampled historical GEFS APCP inventory ranges were about 0.26–0.48 MiB;
0.65 MiB remains a deliberately conservative planning assumption, not a
guaranteed maximum.

Before any acquisition, inspect a few representative dates' GFS and GEFS
`.idx` files (including Day 10) and confirm 2022–2025 retention, accumulation
semantics, and byte sizes. Then narrow dates/members/domain or approve the
cost explicitly. Do not run V2 collection or training until that review.

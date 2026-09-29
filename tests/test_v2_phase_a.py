from copy import deepcopy
from pathlib import Path
import json

import pandas as pd
import pytest

from forecast_bust.acquisition import GribMessage
from forecast_bust.v2.acquisition import _verify_accumulation, download_message, write_missing_era5_month_plans
from forecast_bust.v2.configuration import initialization_dates, load_v2_config
from forecast_bust.v2.dataset import attach_reference_and_error, dataset_manifest, validate_forecast, validate_historical
from forecast_bust.v2.ensemble import add_ensemble_statistics, aggregate_member_daily
from forecast_bust.v2.evaluation import classification_metrics, metrics_by_lead, regression_metrics
from forecast_bust.v2.feature_schema import forecast_feature_schema
from forecast_bust.v2.geography import (configured_grid_centers, contains_grid_center, select_state_cells,
                                        state_reliability_summary, validate_full_grid_coverage)
from forecast_bust.v2.planning import MessageJob, estimate_acquisition, message_jobs
from forecast_bust.v2.splitting import split_historical_periods
from forecast_bust.v2.versioning import model_metadata, resolve_ready_artifact


def tiny_config(tmp_path):
    config = deepcopy(load_v2_config())
    config["time"]["start_date"] = "2025-07-01"
    config["time"]["end_date"] = "2025-07-01"
    config["paths"]["raw_dir"] = str(tmp_path / "raw")
    config["paths"]["legacy_gfs_dir"] = str(tmp_path / "legacy")
    return config


def test_v2_seasonal_dates_and_offline_estimator(tmp_path):
    config = load_v2_config()
    dates = initialization_dates(config)
    assert len(dates) == 56
    assert dates[0] == "2022-07-01" and dates[-1] == "2025-09-30"
    small = tiny_config(tmp_path)
    plan = estimate_acquisition(small)
    assert plan["INITIALIZATIONS"] == 1 and plan["LEADS"] == 10
    assert plan["GFS_MESSAGES"] == 170
    assert plan["GEFS_MESSAGES"] == 31 * 40
    assert plan["ERA5_MONTHS"] == 1
    assert plan["GRID_CELLS_PER_LEAD"] == 125 * 121
    assert plan["NEW_REQUESTS"] == 170 + 31 * 40 + 1
    assert all(".idx" not in job.url for job in message_jobs(small))


def test_gefs_interval_inventory_and_complete_daily_aggregation(tmp_path):
    job = MessageJob("gefs", "2025-07-01", 24, "precipitation", "https://example.org/grib",
                     ":APCP:surface:", tmp_path / "grib", "p01", 18)
    _verify_accumulation(job, "APCP:surface:18-24 hour acc fcst:ENS=+1")
    with pytest.raises(ValueError, match="does not match"):
        _verify_accumulation(job, "APCP:surface:0-24 hour acc fcst:ENS=+1")
    rows = []
    for member, amount in (("c00", 2.0), ("p01", 4.0)):
        for end in (6, 12, 18, 24):
            rows.append({"initialization_time": "2025-07-01T00:00:00Z", "lead_day": 1,
                         "latitude": 20.0, "longitude": 76.0, "member": member,
                         "start_hour": end - 6, "end_hour": end, "apcp_mm": amount})
    intervals = pd.DataFrame(rows)
    daily = aggregate_member_daily(intervals)
    assert daily.gefs_member_precipitation_mm.tolist() == [8.0, 16.0]
    forecast = pd.DataFrame([{"initialization_time": pd.Timestamp("2025-07-01T00:00:00Z"),
                              "lead_day": 1, "latitude": 20.0, "longitude": 76.0,
                              "forecast_precipitation": 12.0}])
    featured = add_ensemble_statistics(forecast, daily, ["c00", "p01"], [10.0])
    assert featured.gefs_precipitation_mean_mm.iloc[0] == 12.0
    assert featured.gefs_precipitation_std_mm.iloc[0] == 4.0
    assert featured["gefs_fraction_ge_10mm"].iloc[0] == .5
    assert featured.gfs_minus_gefs_mean_precipitation_mm.iloc[0] == 0.0
    with pytest.raises(ValueError, match="Incomplete"):
        aggregate_member_daily(intervals.iloc[:-1])
    with pytest.raises(ValueError, match="target/reference"):
        add_ensemble_statistics(forecast.assign(reference_precipitation=1), daily, ["c00", "p01"], [10.0])
    with pytest.raises(ValueError, match="membership"):
        add_ensemble_statistics(forecast, daily[daily.member == "c00"], ["c00", "p01"], [10.0])


def _forecast_row(day="2025-07-01", lead=1):
    return {"initialization_time": pd.Timestamp(day, tz="UTC"),
            "valid_time": pd.Timestamp(day, tz="UTC") + pd.Timedelta(days=lead),
            "latitude": 20.0, "longitude": 76.0, "lead_day": lead,
            "forecast_precipitation": 12.0, "forecast_temperature_2m": 300.0,
            "forecast_relative_humidity_2m": 80.0, "forecast_mean_sea_level_pressure": 100000.0,
            "forecast_u_wind_10m": 2.0, "forecast_v_wind_10m": 3.0,
            "forecast_wind_speed_10m": 3.6055, "precipitation_gradient_mm_per_degree": 1.0,
            "gefs_precipitation_cv": float("nan")}


def test_v2_schema_exact_reference_expected_error_and_manifest(tmp_path):
    forecast = validate_forecast(pd.DataFrame([_forecast_row()]), ["gefs_precipitation_cv"])
    reference = pd.DataFrame([{"valid_time": forecast.valid_time.iloc[0], "latitude": 20.0,
                               "longitude": 76.0, "reference_precipitation": 4.0}])
    historical = attach_reference_and_error(forecast, reference)
    assert historical.absolute_error.iloc[0] == historical.target_absolute_error_mm.iloc[0] == 8.0
    validate_historical(historical, ["gefs_precipitation_cv"])
    with pytest.raises(ValueError, match="target"):
        validate_forecast(forecast.assign(is_bust=1), [])
    with pytest.raises(ValueError, match="exact ERA5"):
        attach_reference_and_error(forecast, reference.assign(latitude=21))
    with pytest.raises(ValueError, match="inconsistent"):
        validate_historical(historical.assign(target_absolute_error_mm=7), ["gefs_precipitation_cv"])
    data_path, config_path = tmp_path / "dataset.csv", tmp_path / "config.yaml"
    historical.to_csv(data_path, index=False)
    config_path.write_text("version: v2", encoding="utf-8")
    manifest = dataset_manifest(data_path, config_path, historical)
    assert manifest["rows"] == 1 and len(manifest["dataset_sha256"]) == 64


def test_v2_temporal_split_by_initialization_with_verification_embargo():
    frame = pd.DataFrame([_forecast_row("2022-07-01", 10), _forecast_row("2024-07-01", 10),
                          _forecast_row("2025-07-01", 10)])
    settings = load_v2_config()["evaluation"]
    train, validation, test = split_historical_periods(frame, settings)
    assert [len(train), len(validation), len(test)] == [1, 1, 1]
    with pytest.raises(ValueError, match="embargo"):
        split_historical_periods(frame, {**settings, "embargo_days": 0})


def test_state_grid_membership_and_partial_summary():
    square = {"type": "Polygon", "coordinates": [[[75.5, 19.5], [76.5, 19.5],
               [76.5, 20.5], [75.5, 20.5], [75.5, 19.5]]]}
    assert contains_grid_center(square, 20, 76)
    assert not contains_grid_center(square, 22, 78)
    rows = []
    for lead in range(1, 11):
        rows.extend([{"initialization_time": "2025-07-01T00:00:00Z", "lead_day": lead,
                      "latitude": latitude, "longitude": longitude, "bust_probability": .1 * lead,
                      "confidence_score": 100 - 10 * lead, "is_bust_predicted": lead >= 5}
                     for latitude, longitude in ((20.0, 76.0), (22.0, 78.0))])
    frame = pd.DataFrame(rows)
    assert len(select_state_cells(frame, "Example", {"Example": square})) == 10
    summary = state_reliability_summary(frame, "Example", {"Example": square},
                                        {"south": 20, "north": 24, "west": 76, "east": 80})
    assert summary["coverage"] == "partial_grid_domain"
    assert summary["grid_cell_count"] == 1 and summary["lowest_confidence_lead"] == 10
    assert summary["days"][4]["percentage_predicted_bust"] == 100
    tiny_grid = {"south": 20, "north": 20.25, "west": 76, "east": 76.25, "grid_resolution_degrees": .25}
    latitudes, longitudes = configured_grid_centers(tiny_grid)
    assert latitudes == [20, 20.25] and longitudes == [76, 76.25]
    complete = pd.DataFrame([{"initialization_time": "2025-07-01", "lead_day": 1,
                              "latitude": lat, "longitude": lon} for lat in latitudes for lon in longitudes])
    validate_full_grid_coverage(complete, tiny_grid)
    with pytest.raises(ValueError, match="Incomplete"):
        validate_full_grid_coverage(complete.iloc[:-1], tiny_grid)


def test_v1_rollback_registry_and_v2_readiness_guard():
    assert model_metadata("v1")["feature_schema_version"] == "1.0"
    assert Path(resolve_ready_artifact("v1")).is_file()
    v2 = model_metadata("v2")
    if v2["status"] == "planned":
        with pytest.raises(ValueError, match="not trained"):
            resolve_ready_artifact("v2")
    else:
        assert v2["status"] == "ready"
        assert Path(resolve_ready_artifact("v2")).is_file()


def test_v2_feature_contract_and_per_lead_metrics():
    schema = forecast_feature_schema(load_v2_config())
    assert "forecast_cape_surface" in schema and "forecast_vertical_velocity_700mb" in schema
    assert "gefs_precipitation_std_mm" in schema and "target_absolute_error_mm" not in schema
    result = classification_metrics([0, 1], [.1, .9], .5)
    assert result["pr_auc"] == result["roc_auc"] == 1.0
    assert result["brier_score"] > 0
    regression = regression_metrics([2, 8], [3, 6])
    assert regression["mae_mm"] == 1.5 and regression["median_absolute_error_mm"] == 1.5
    frame = pd.DataFrame({"lead_day": [1, 5], "is_bust": [0, 1], "target_absolute_error_mm": [2, 8]})
    by_lead = metrics_by_lead(frame, [.1, .9], [3, 6], .5)
    assert set(by_lead) == {"1", "5"}


def test_range_download_resumes_only_matching_partial_inventory(tmp_path, monkeypatch):
    import forecast_bust.v2.acquisition as acquisition

    target = tmp_path / "test.grb2"
    job = MessageJob("gefs", "2025-07-01", 24, "precipitation", "https://example.org/grib",
                     ":APCP:surface:", target, "p01", 18)
    description = "APCP:surface:18-24 hour acc fcst:ENS=+1"
    monkeypatch.setattr(acquisition, "_inspect_message", lambda *_: GribMessage(100, 111, description))
    part = target.with_suffix(".grb2.part")
    part.write_bytes(b"GRIBAB")
    part.with_suffix(".part.json").write_text(json.dumps({"url": job.url, "start": 100, "end": 111,
                                                          "size": 12, "description": description}), encoding="utf-8")
    seen = []

    class Response:
        status_code = 206
        headers = {"Content-Range": "bytes 106-111/1000"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def raise_for_status(self): return None
        def iter_content(self, chunk_size): yield b"CD7777"

    def fake_get(url, headers, **_):
        seen.append((url, headers["Range"]))
        return Response()

    monkeypatch.setattr(acquisition.requests, "get", fake_get)
    assert download_message(job) == target
    assert seen == [(job.url, "bytes=106-111")]
    assert target.read_bytes() == b"GRIBABCD7777"
    assert download_message(job) == target  # Verified complete cache: no new request.
    assert len(seen) == 1


def test_missing_era5_month_plan_is_bounded_and_does_not_submit(tmp_path):
    config = tiny_config(tmp_path)
    plans = write_missing_era5_month_plans(config)
    assert len(plans) == 1 and plans[0]["month"] == "202507"
    request = json.loads(plans[0]["request_path"].read_text(encoding="utf-8"))
    assert request["request"]["variable"] == ["total_precipitation"]
    assert request["request"]["area"] == [37.0, 68.0, 6.0, 98.0]

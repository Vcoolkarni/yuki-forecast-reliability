"""Tests for additive product services, without model fitting or downloads."""

import math

import pandas as pd
import pytest

from forecast_bust.api.analogs import AnalogRepository
from forecast_bust.api.brief import create_brief
from forecast_bust.api.comparison import compare_runs


def _forecast(init, precip, temperature=300, humidity=70, latitude=22):
    return {"initialization_time": init, "valid_time": "2026-07-02T00:00:00Z", "lead_day": 1,
            "latitude": latitude, "longitude": 78.0, "forecast_precipitation": precip,
            "forecast_temperature_2m": temperature, "forecast_relative_humidity_2m": humidity,
            "forecast_mean_sea_level_pressure": 100000.0, "forecast_u_wind_10m": 3.0,
            "forecast_v_wind_10m": 4.0, "forecast_wind_speed_10m": 5.0,
            "precipitation_gradient_mm_per_degree": 2.0}


def test_analog_rank_excludes_current_event_and_uses_forecast_only(tmp_path):
    query = _forecast("2026-07-01T00:00:00Z", 10)
    rows = [
        {**query, "reference_precipitation": 99, "absolute_error": 89, "is_bust": 1},
        {**_forecast("2026-07-04T00:00:00Z", 11), "reference_precipitation": 11, "absolute_error": 0, "is_bust": 0},
        {**_forecast("2026-07-07T00:00:00Z", 30), "reference_precipitation": 5, "absolute_error": 25, "is_bust": 1},
    ]
    path = tmp_path / "historical.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    result = AnalogRepository(path).retrieve(query, 2)
    assert [row["initialization_time"][:10] for row in result["analogs"]] == ["2026-07-04", "2026-07-07"]
    assert result["percentage_busted"] == 50
    assert result["mean_historical_absolute_error"] == 12.5
    assert result["analogs"][0]["distance"] < result["analogs"][1]["distance"]
    assert "ERA5 reanalysis" in result["provenance"]
    # Reference outcomes must have zero effect on similarity distances or ordering.
    rows[1]["reference_precipitation"] = 1000
    rows[1]["absolute_error"] = 989
    rows[1]["is_bust"] = 1
    pd.DataFrame(rows).to_csv(path, index=False)
    changed = AnalogRepository(path).retrieve(query, 2)
    assert [item["distance"] for item in result["analogs"]] == [item["distance"] for item in changed["analogs"]]
    assert changed["percentage_busted"] == 100


def test_analog_feature_normalization(tmp_path):
    query = _forecast("2026-07-01T00:00:00Z", 10)
    rows = [
        {**_forecast("2026-07-04T00:00:00Z", 11, 300), "reference_precipitation": 0, "absolute_error": 11, "is_bust": 0},
        {**_forecast("2026-07-07T00:00:00Z", 10, 301), "reference_precipitation": 0, "absolute_error": 10, "is_bust": 0},
        {**_forecast("2026-07-10T00:00:00Z", 30, 300), "reference_precipitation": 0, "absolute_error": 30, "is_bust": 1},
    ]
    path = tmp_path / "historical.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    result = AnalogRepository(path).retrieve(query, 3)
    # Normalize by each historical forecast feature's standard deviation;
    # 1 K of temperature is therefore more distinctive than 1 mm of rain.
    assert result["analogs"][0]["initialization_time"].startswith("2026-07-04")
    rain_std = pd.Series([11, 10, 30]).std(ddof=0)
    assert math.isclose(result["analogs"][0]["distance"], 1 / rain_std)


def test_comparison_requires_matched_grid_and_does_not_use_reference():
    old = {"initialization_time": "2026-07-01T00:00:00Z", "records": [
        {"lead_day": 1, "latitude": 20, "longitude": 76, "bust_probability": .2,
         "confidence_score": 80, "is_bust_predicted": False}], "hotspots": []}
    new = {"initialization_time": "2026-07-04T00:00:00Z", "records": [
        {"lead_day": 1, "latitude": 20, "longitude": 76, "bust_probability": .7,
         "confidence_score": 30, "is_bust_predicted": True}], "hotspots": []}
    result = compare_runs(new, old, 1)
    assert result["emerging_bust_cells"] == 1
    assert result["mean_probability_delta"] == pytest.approx(.5)
    assert result["mean_confidence_delta"] == pytest.approx(-50)
    assert result["new_hotspot_regions"] == 0
    new["records"][0]["longitude"] = 77
    with pytest.raises(ValueError, match="same grid"):
        compare_runs(new, old, 1)


def test_comparison_tracks_nonoverlapping_hotspot_regions():
    row = {"lead_day": 1, "latitude": 20, "longitude": 76, "bust_probability": .3,
           "confidence_score": 70, "is_bust_predicted": True}
    before = {"initialization_time": "2026-07-01T00:00:00Z", "records": [row], "hotspots": [
        {"lead_day": 1, "bounding_box": {"south": 20, "north": 20.25, "west": 76, "east": 76.25}}]}
    after = {"initialization_time": "2026-07-04T00:00:00Z", "records": [row], "hotspots": [
        {"lead_day": 1, "bounding_box": {"south": 23, "north": 23.25, "west": 79, "east": 79.25}}]}
    result = compare_runs(after, before, 1)
    assert result["hotspot_count_delta"] == 0
    assert result["new_hotspot_regions"] == 1
    assert result["resolved_hotspot_regions"] == 1


def test_brief_is_deterministic_and_inference_only():
    row = {"lead_day": 2, "latitude": 22.5, "longitude": 78.0, "bust_probability": .64,
           "confidence_category": "Low", "explanations": [{"feature": "forecast_precipitation"}]}
    artifact = {"initialization_time": "2026-07-01T00:00:00Z", "records": [row],
        "lead_day_summaries": [{"lead_day": 2, "mean_confidence": 36, "mean_bust_probability": .64,
                                "hotspot_count": 1, "highest_risk_location": {"latitude": 22.5,
                                "longitude": 78, "lead_day": 2, "bust_probability": .64}}]}
    result = create_brief(artifact, 2)
    assert "64.0%" in result["text"]
    assert "22.50°N" in result["text"]
    assert result == create_brief(artifact, 2)

"""Small deterministic fixtures verify output contracts, not meteorological skill."""
from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

from forecast_bust.features import FEATURE_COLUMNS
from forecast_bust.inference import ForecastInference
from forecast_bust.inference.hotspots import find_hotspots
from forecast_bust.inference.service import DEFAULT_CONFIG, confidence_from_probability


class StubBooster:
    def predict(self, matrix, pred_contribs=False):
        assert pred_contribs
        values = np.zeros((matrix.num_row(), matrix.num_col() + 1))
        values[:, 3] = 0.8
        values[:, 4] = -0.4
        values[:, -1] = -1.0
        return values


class StubModel:
    classes_ = np.array([0, 1])

    def predict_proba(self, inputs):
        p = np.full(len(inputs), 0.3)
        return np.column_stack([1 - p, p])

    def get_booster(self):
        return StubBooster()


class StubCalibrator:
    classes_ = np.array([0, 1])

    def predict_proba(self, logits):
        p = 1 / (1 + np.exp(-(logits[:, 0] - 1)))
        return np.column_stack([1 - p, p])


@pytest.fixture
def bundle():
    return {"model": StubModel(), "calibrator": StubCalibrator(),
            "features": FEATURE_COLUMNS.copy(), "decision_threshold": 0.1}


@pytest.fixture
def forecast():
    rows = []
    for lead in range(1, 11):
        for latitude in [20.0, 20.25, 20.5]:
            for longitude in [76.0, 76.25, 76.5]:
                rows.append({
                    "initialization_time": "2026-07-01T00:00:00Z",
                    "valid_time": (pd.Timestamp("2026-07-01", tz="UTC") + pd.Timedelta(days=lead)).isoformat(),
                    "lead_day": lead, "latitude": latitude, "longitude": longitude,
                    "forecast_precipitation": 30.0, "forecast_temperature_2m": 300.0,
                    "forecast_relative_humidity_2m": 70.0, "forecast_mean_sea_level_pressure": 100000.0,
                    "forecast_u_wind_10m": 3.0, "forecast_v_wind_10m": 4.0,
                    "forecast_wind_speed_10m": 5.0, "precipitation_gradient_mm_per_degree": 0.0,
                })
    return pd.DataFrame(rows)


def test_probabilities_confidence_threshold_and_ten_day_output(bundle, forecast):
    result = ForecastInference(bundle).predict_initialization(forecast)
    expected_p = 1 / (1 + np.exp(-(np.log(0.3 / 0.7) - 1)))
    assert len(result["records"]) == 90
    assert [day["lead_day"] for day in result["lead_day_summaries"]] == list(range(1, 11))
    assert result["initialization_summary"]["grid_cell_count"] == 9
    for record in result["records"]:
        assert 0 <= record["bust_probability"] <= 1
        assert record["bust_probability"] == pytest.approx(expected_p)
        assert 0 <= record["confidence_score"] <= 100
        assert record["confidence_score"] == pytest.approx(100 * (1 - expected_p))
        assert record["decision_threshold"] == 0.1
        assert record["is_bust_predicted"] is True  # Both raw/calibrated are below 0.5.
        assert record["confidence_category"] == "High"
    json.dumps(result, allow_nan=False)


def test_required_fields_and_explanations(bundle, forecast):
    record = ForecastInference(bundle).predict_initialization(forecast)["records"][0]
    assert set(forecast.columns) <= set(record)
    assert {"decision_threshold", "is_bust_predicted", "confidence_category", "confidence_score", "bust_probability"} <= set(record)
    assert len(record["explanations"]) == 3
    explanation = record["explanations"][0]
    assert explanation == {"feature": "forecast_precipitation", "feature_value": 30.0,
                           "contribution": 0.8, "direction": "increases_model_bust_score"}
    assert record["explanations"][1]["direction"] == "decreases_model_bust_score"
    assert "forecast_precipitation" in record["explanation_summary"]
    assert "not meteorological causes" in record["explanation_summary"]


@pytest.mark.parametrize("column", ["reference_precipitation", "forecast_error", "absolute_error", "is_bust"])
def test_target_input_rejected(bundle, forecast, column):
    forecast[column] = 0
    with pytest.raises(ValueError, match="target/reference"):
        ForecastInference(bundle).predict_initialization(forecast)


def test_target_model_feature_and_missing_threshold_rejected(bundle):
    invalid = dict(bundle, features=bundle["features"] + ["absolute_error"])
    with pytest.raises(ValueError, match="leakage"):
        ForecastInference(invalid)
    bundle.pop("decision_threshold")
    with pytest.raises(ValueError, match="decision_threshold"):
        ForecastInference(bundle)


def test_missing_predictor_or_lead_rejected(bundle, forecast):
    with pytest.raises(ValueError, match="Missing required forecast"):
        ForecastInference(bundle).predict_initialization(forecast.drop(columns="forecast_temperature_2m"))
    with pytest.raises(ValueError, match="1 through 10"):
        ForecastInference(bundle).predict_initialization(forecast[forecast.lead_day < 10])


def test_existing_derivation_used_when_derived_fields_missing(bundle, forecast):
    result = ForecastInference(bundle).predict_initialization(forecast.drop(columns=[
        "forecast_wind_speed_10m", "precipitation_gradient_mm_per_degree"]))
    assert result["records"][0]["forecast_wind_speed_10m"] == 5.0
    assert result["records"][0]["precipitation_gradient_mm_per_degree"] == 0.0


def test_hotspots_four_neighbors_and_minimum_size(forecast):
    grid = forecast[forecast.lead_day == 1].reset_index(drop=True).copy()
    grid["bust_probability"] = 0.1
    grid.loc[[0, 1, 8], "bust_probability"] = [0.7, 0.8, 0.9]
    grid["confidence_score"] = confidence_from_probability(grid.bust_probability)
    result = find_hotspots(grid, 0.6, min_cells=2, connectivity=4)
    assert len(result) == 1
    assert result[0]["number_of_cells"] == 2
    assert result[0]["mean_bust_probability"] == pytest.approx(0.75)
    assert result[0]["max_bust_probability"] == 0.8
    assert result[0]["centroid_longitude"] == pytest.approx(76.125)
    assert result[0]["mean_confidence"] == pytest.approx(25)
    assert result[0]["bounding_box"] == {"south": 20.0, "north": 20.0, "west": 76.0, "east": 76.25}
    assert result[0]["member_cells"] == [{"latitude": 20.0, "longitude": 76.0},
                                          {"latitude": 20.0, "longitude": 76.25}]
    grid["bust_probability"] = 0.1
    grid.loc[[0, 4], "bust_probability"] = 0.8
    assert find_hotspots(grid, 0.6, 2, 4) == []
    assert len(find_hotspots(grid, 0.6, 2, 8)) == 1


def test_configurable_confidence_categories(bundle, forecast):
    config = deepcopy(DEFAULT_CONFIG)
    config["confidence"] = {"high_min": 95, "moderate_min": 85}
    assert ForecastInference(bundle, config).predict_initialization(forecast)["records"][0]["confidence_category"] == "Moderate"
    config["confidence"]["moderate_min"] = 90
    assert ForecastInference(bundle, config).predict_initialization(forecast)["records"][0]["confidence_category"] == "Low"


@pytest.mark.parametrize("probability", [[-0.1], [1.1], [float("nan")], [float("inf")]])
def test_invalid_probability_rejected(probability):
    with pytest.raises(ValueError, match="within"):
        confidence_from_probability(probability)


def test_confidence_endpoints():
    assert confidence_from_probability([0, 0.5, 1]).tolist() == [100, 50, 0]


def test_multiple_initializations_invalid_time_and_incomplete_grid(bundle, forecast):
    invalid = forecast.copy()
    invalid.loc[0, "initialization_time"] = "2026-07-02T00:00:00Z"
    with pytest.raises(ValueError, match="one initialization"):
        ForecastInference(bundle).predict_initialization(invalid)
    invalid = forecast.copy()
    invalid.loc[0, "valid_time"] = "2026-07-04T00:00:00Z"
    with pytest.raises(ValueError, match="valid_time"):
        ForecastInference(bundle).predict_initialization(invalid)
    with pytest.raises(ValueError, match="rectangular grid"):
        ForecastInference(bundle).predict_initialization(forecast.iloc[1:])

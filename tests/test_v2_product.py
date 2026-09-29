"""Operational V2 regression tests using the frozen model and 2024 demo only."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from forecast_bust.api.app import create_app
from forecast_bust.api.v2_routes import state_metrics
from forecast_bust.v2.inference import V2Inference


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data/interim/v2_historical_demo_forecasts.csv.gz"
MODEL = ROOT / "models/v2/recommended_0p50/frozen_selection.json"
pytestmark = pytest.mark.skipif(not DEMO.is_file() or not MODEL.is_file(),
                                reason="Frozen V2 model and forecast-only historical demo are required")


@pytest.fixture(scope="module")
def artifact():
    service = V2Inference(MODEL.parent, ROOT / "config/inference.yaml")
    frame = pd.read_csv(DEMO)
    selected = frame.loc[frame.initialization_time == frame.initialization_time.iloc[0]]
    return service, selected, service.predict_initialization(selected)


def test_v2_frozen_forecast_only_inference(artifact):
    service, forecast, result = artifact
    assert len(result["records"]) == 38430
    assert [item["lead_day"] for item in result["lead_day_summaries"]] == list(range(1, 11))
    assert sum(item["lead_day"] == 1 for item in result["records"]) == 3843
    assert sum(item["lead_day"] == 10 for item in result["records"]) == 3843
    assert result["decision_threshold"] == service.threshold
    for row in (result["records"][0], result["records"][-1]):
        assert 0 <= row["bust_probability"] <= 1
        assert row["confidence_score"] == pytest.approx(100 * (1 - row["bust_probability"]))
        assert row["is_bust_predicted"] == (row["bust_probability"] >= service.threshold)
        assert row["expected_absolute_error_mm"] >= 0
        assert row["gefs_end_window_spread_6h_mm"] >= 0
        assert row["explanations"] and row["explanation_summary"]
        assert not {"reference_precipitation", "forecast_error", "absolute_error", "is_bust"} & row.keys()
    assert result["hotspots"] and all(item["number_of_cells"] >= 2 for item in result["hotspots"])
    with pytest.raises(ValueError, match="rejects"):
        service.predict_initialization(forecast.assign(reference_precipitation=0))


def test_v2_state_aggregation_uses_multiple_cells(artifact):
    _, _, result = artifact
    rows = [item for item in result["records"] if item["lead_day"] == 1][:2]
    members = {(item["latitude"], item["longitude"]) for item in rows}
    state = state_metrics(result, "Example", members, 1)
    assert state["grid_cell_count"] == 2
    assert state["mean_forecast_confidence"] == pytest.approx(
        sum(item["confidence_score"] for item in rows) / 2)
    assert state["highest_risk_cell"]["bust_probability"] == max(item["bust_probability"] for item in rows)


def test_v2_api_and_v1_backwards_compatibility():
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/forecast/2026-09-12/summary").status_code in (200, 404)
        health = client.get("/api/v2/health")
        assert health.status_code == 200
        assert health.json()["source_kind"] == ("mixed" if health.json()["run_metadata"] and
                                                any(item["run_kind"] == "current_forecast" for item in health.json()["run_metadata"].values())
                                                else "historical_demo")
        states = client.get("/api/v2/states").json()["states"]
        assert len(states) == 36
        assert any(item["grid_cell_count"] == 0 for item in states)
        initialization = "2024-09-29"
        summary = client.get(f"/api/v2/forecast/{initialization}/summary")
        assert summary.status_code == 200
        for lead in (1, 10):
            response = client.get(f"/api/v2/forecast/{initialization}/day/{lead}")
            assert response.status_code == 200 and len(response.json()["records"]) == 3843
            assert response.headers["content-encoding"] == "gzip"
            row = response.json()["records"][0]
            assert row["expected_absolute_error_mm"] >= 0 and row["explanations"]
            assert "reference_precipitation" not in row and "is_bust" not in row
        state = client.get(f"/api/v2/forecast/{initialization}/state/Madhya%20Pradesh/day/10")
        assert state.status_code == 200 and state.json()["grid_cell_count"] > 1
        assert client.get(f"/api/v2/forecast/{initialization}/state/Delhi/day/1").status_code == 409
        assert client.get(f"/api/v2/forecast/{initialization}/day/11").status_code == 422
        assert client.get(f"/api/v2/forecast/{initialization}/cell?latitude=20.1&longitude=76&lead_day=1").status_code == 404
        assert client.get("/api/v2/forecast/2024-01-01/summary").status_code == 404

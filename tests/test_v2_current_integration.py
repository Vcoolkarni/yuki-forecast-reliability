"""Published 2026 forecast-only run; never reads 2025 final-test labels."""

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from forecast_bust.api.app import create_app
from forecast_bust.v2.dataset import TARGETS, validate_forecast
from forecast_bust.v2.geography import validate_full_grid_coverage

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "data/processed/v2/current/latest.json"
pytestmark = pytest.mark.skipif(not LATEST.is_file(), reason="No complete current NOAA run is published")


def test_published_current_run_is_complete_forecast_only_and_immutable():
    pointer = json.loads(LATEST.read_text(encoding="utf-8"))
    folder = LATEST.parent / "runs" / pointer["run_id"]
    manifest_path = folder / "manifest.json"
    assert sha256(manifest_path.read_bytes()).hexdigest() == pointer["manifest_sha256"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and manifest["run_kind"] == "current_forecast"
    assert manifest["records"] == 38430 and len(manifest["component_hours"]) == 10
    for lead in (1, 10):
        item = manifest["component_hours"][str(lead)]
        assert item["gfs_apcp_component_forecast_hours"] == [24 * (lead - 1) + h for h in (6, 12, 18, 24)]
        assert item["gefs_mean_component_forecast_hours"] == item["gfs_apcp_component_forecast_hours"]
        assert item["gefs_spread_component_forecast_hours"] == [24 * lead]
    features = folder / "features.csv.gz"
    assert sha256(features.read_bytes()).hexdigest() == manifest["artifacts"][features.name]["sha256"]
    frame = pd.read_csv(features)
    assert not set(frame) & TARGETS
    validate_forecast(frame, manifest["feature_names_ordered"])
    validate_full_grid_coverage(frame, manifest["grid"])
    assert len(frame) == 38430 and set(frame.lead_day) == set(range(1, 11))
    init = pd.Timestamp(manifest["initialization_utc"])
    assert set(pd.to_datetime(frame.loc[frame.lead_day == 1, "valid_time"], utc=True)) == {init + timedelta(days=1)}
    assert set(pd.to_datetime(frame.loc[frame.lead_day == 10, "valid_time"], utc=True)) == {init + timedelta(days=10)}


def test_current_api_preserves_demos_and_rejects_cross_kind_comparison():
    pointer = json.loads(LATEST.read_text(encoding="utf-8"))
    initialization = (LATEST.parent / "runs" / pointer["run_id"] / "manifest.json")
    key = json.loads(initialization.read_text(encoding="utf-8"))["initialization_utc"]
    with TestClient(create_app()) as client:
        health = client.get("/api/v2/health").json()
        assert health["primary_initialization"] == key
        assert health["run_metadata"][key]["run_kind"] == "current_forecast"
        assert all(health["run_metadata"][demo]["run_kind"] == "historical_demo" for demo in
                   ("2024-09-26T00:00:00Z", "2024-09-29T00:00:00Z"))
        metadata = client.get(f"/api/v2/runs/{key}/metadata").json()
        assert metadata["source_kind"] == "current_forecast"
        for lead in (1, 10):
            result = client.get(f"/api/v2/forecast/{key}/day/{lead}")
            assert result.status_code == 200 and result.headers["content-encoding"] == "gzip"
            assert result.json()["source_kind"] == "current_forecast"
            assert len(result.json()["records"]) == 3843
            row = result.json()["records"][0]
            assert row["confidence_score"] == pytest.approx(100 * (1 - row["bust_probability"]))
            assert row["is_bust_predicted"] == (row["bust_probability"] >= row["decision_threshold"])
            assert row["expected_absolute_error_mm"] >= 0
            assert row["gefs_end_window_spread_6h_mm"] >= 0
            assert row["explanations"] and not set(row) & TARGETS
        state = client.get(f"/api/v2/forecast/{key}/state/Madhya%20Pradesh/day/10")
        assert state.status_code == 200 and state.json()["grid_cell_count"] == 107
        assert client.get(f"/api/v2/forecast/{key}/state/Delhi/day/1").status_code == 409
        cross = client.get("/api/v2/compare", params={"current_initialization": key,
            "previous_initialization": "2024-09-29T00:00:00Z", "lead_day": 1})
        assert cross.status_code == 422
        demo = client.get("/api/v2/runs/2024-09-29T00:00:00Z/metadata")
        assert demo.status_code == 200 and demo.json()["source_kind"] == "historical_demo"

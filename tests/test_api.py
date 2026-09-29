"""HTTP contract tests; install the declared API dependencies to execute."""
from pathlib import Path
from copy import deepcopy

import pytest

pytest.importorskip("fastapi", reason="Install FastAPI dependencies to run HTTP endpoint tests")
pytest.importorskip("httpx", reason="HTTPX is required for TestClient")

from fastapi.testclient import TestClient

from forecast_bust.api.app import create_app
from forecast_bust.api.repository import normalize_initialization
from forecast_bust.api.settings import APISettings


@pytest.fixture
def client():
    # A complete typed service-output fixture tests the transport without fitting a model.
    record = {
        "initialization_time": "2026-09-12T00:00:00Z", "valid_time": "2026-09-13T00:00:00Z",
        "lead_day": 1, "latitude": 20.0, "longitude": 76.0,
        "forecast_precipitation": 1.0, "forecast_temperature_2m": 300.0,
        "forecast_relative_humidity_2m": 70.0, "forecast_mean_sea_level_pressure": 100000.0,
        "forecast_u_wind_10m": 3.0, "forecast_v_wind_10m": 4.0,
        "forecast_wind_speed_10m": 5.0, "precipitation_gradient_mm_per_degree": 0.0,
        "bust_probability": 0.2, "confidence_score": 80.0, "confidence_category": "High",
        "is_bust_predicted": False, "decision_threshold": 0.25,
        "explanations": [{"feature": "forecast_precipitation", "feature_value": 1.0,
                          "contribution": 0.1, "direction": "increases_model_bust_score"}],
        "explanation_summary": "Factors influencing the model prediction.", "explanation_base_value": -1.0,
    }
    records = []
    days = []
    for lead in range(1, 11):
        for y in range(17):
            for x in range(17):
                records.append({**record, "lead_day": lead, "valid_time": f"2026-09-{12+lead:02d}T00:00:00Z",
                                "latitude": 20 + 0.25*y, "longitude": 76 + 0.25*x})
        days.append({"lead_day": lead, "number_of_predictions": 289, "mean_bust_probability": 0.2,
                     "maximum_bust_probability": 0.2, "mean_confidence": 80.0, "percentage_predicted_bust": 0.0,
                     "hotspot_count": 0, "highest_risk_location": {
                         "latitude": 20.0, "longitude": 76.0, "lead_day": lead, "bust_probability": 0.2}})
    artifact = {
        "initialization_time": record["initialization_time"], "model_id": "fixture", "decision_threshold": 0.25,
        "records": records, "hotspots": [], "lead_day_summaries": days,
        "initialization_summary": {key: value for key, value in days[0].items() if key != "lead_day"},
    }
    artifact["initialization_summary"].update(number_of_predictions=2890, lead_day_count=10, grid_cell_count=289)
    earlier = deepcopy(artifact)
    earlier["initialization_time"] = "2026-09-11T00:00:00Z"
    for item in earlier["records"]:
        item["initialization_time"] = earlier["initialization_time"]
    earlier["records"][0]["bust_probability"] = 0.4
    earlier["records"][0]["confidence_score"] = 60.0
    earlier["records"][0]["is_bust_predicted"] = True

    class Store:
        def initialize(self): pass
        def get(self, initialization):
            key = normalize_initialization(initialization)
            if key == earlier["initialization_time"]:
                return earlier
            if key == record["initialization_time"]:
                return artifact
            raise KeyError(initialization)
        def health(self):
            return {"api_ready": True, "model_ready": True, "forecast_ready": True, "status": "ready",
                    "model_id": "fixture", "decision_threshold": 0.25, "features": ["forecast_precipitation"],
                    "available_initializations": [earlier["initialization_time"], record["initialization_time"]], "cached_initializations": 0,
                    "grid": {"south": 20, "north": 24, "west": 76, "east": 80,
                             "latitude_step_degrees": .25, "longitude_step_degrees": .25}}

    settings = APISettings(Path("model"), Path("forecast"), Path("config"), 4, ("http://localhost:5173",))
    with TestClient(create_app(settings, Store())) as active:
        yield active


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["model_ready"]
    assert response.json()["decision_threshold"] == 0.25
    assert response.json()["grid"]["latitude_step_degrees"] == 0.25


def test_day_payload_supports_http_compression(client):
    response = client.get("/api/v1/forecast/2026-09-12/day/1", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert len(response.json()["records"]) == 289


def test_summary(client):
    response = client.get("/api/v1/forecast/2026-09-12/summary")
    assert response.status_code == 200
    assert len(response.json()["lead_day_summaries"]) == 10
    assert response.json()["initialization_summary"]["number_of_predictions"] == 2890


def test_day(client):
    response = client.get("/api/v1/forecast/2026-09-12/day/3")
    assert response.status_code == 200
    assert len(response.json()["records"]) == 289
    assert all(record["lead_day"] == 3 for record in response.json()["records"])


def test_hotspots(client):
    response = client.get("/api/v1/forecast/2026-09-12/day/2/hotspots")
    assert response.status_code == 200
    assert response.json()["hotspots"] == []


def test_highest_risk(client):
    response = client.get("/api/v1/forecast/2026-09-12/day/2/highest-risk")
    assert response.status_code == 200
    assert response.json()["explanations"][0]["feature"] == "forecast_precipitation"


def test_cell_lookup(client):
    response = client.get("/api/v1/forecast/2026-09-12/cell", params={"latitude": 22, "longitude": 78, "lead_day": 5})
    assert response.status_code == 200
    assert response.json()["latitude"] == 22
    assert response.json()["longitude"] == 78
    assert response.json()["lead_day"] == 5
    assert "explanation_summary" in response.json()


def test_timeline(client):
    response = client.get("/api/v1/forecast/2026-09-12/timeline")
    assert response.status_code == 200
    assert [point["lead_day"] for point in response.json()["days"]] == list(range(1, 11))
    assert set(response.json()["days"][0]) == {"lead_day", "mean_bust_probability", "maximum_bust_probability",
                                              "mean_confidence", "percentage_predicted_bust", "hotspot_count"}


@pytest.mark.parametrize("lead", [0, 11, "abc"])
def test_invalid_lead(client, lead):
    assert client.get(f"/api/v1/forecast/2026-09-12/day/{lead}").status_code == 422


def test_invalid_coordinate(client):
    route = "/api/v1/forecast/2026-09-12/cell"
    assert client.get(route, params={"latitude": 22.1, "longitude": 78, "lead_day": 1}).status_code == 404
    assert client.get(route, params={"latitude": 91, "longitude": 78, "lead_day": 1}).status_code == 422
    assert client.get(route, params={"latitude": 22, "longitude": 78, "lead_day": 11}).status_code == 422


def test_invalid_initialization(client):
    assert client.get("/api/v1/forecast/not-a-date/summary").status_code == 422
    assert client.get("/api/v1/forecast/2026-01-01/summary").status_code == 404


def test_no_training_reference_leakage(client):
    forbidden = {"reference_precipitation", "forecast_error", "absolute_error", "is_bust"}
    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for nested in value.values(): check(nested)
        elif isinstance(value, list):
            for nested in value: check(nested)
    for suffix in ("summary", "day/1", "day/1/hotspots", "day/1/highest-risk", "timeline",
                   "cell?latitude=22&longitude=78&lead_day=1"):
        response = client.get(f"/api/v1/forecast/2026-09-12/{suffix}")
        assert response.status_code == 200
        check(response.json())


def test_cors_allowlist(client):
    for origin, allowed in [("http://localhost:5173", True), ("https://other.example", False)]:
        response = client.options("/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert (response.headers.get("access-control-allow-origin") == origin) is allowed


def test_comparison_endpoint(client):
    response = client.get("/api/v1/compare", params={"current_initialization": "2026-09-12",
        "previous_initialization": "2026-09-11", "lead_day": 1})
    assert response.status_code == 200
    result = response.json()
    assert result["number_of_cells"] == 289
    assert result["resolved_bust_cells"] == 1
    assert result["cells"][0]["delta_bust_probability"] == pytest.approx(-0.2)
    assert result["cells"][0]["delta_confidence"] == pytest.approx(20)
    assert client.get("/api/v1/compare", params={"current_initialization": "2026-09-11",
        "previous_initialization": "2026-09-12", "lead_day": 1}).status_code == 422


def test_brief_endpoint(client):
    response = client.get("/api/v1/forecast/2026-09-12/day/1/brief")
    assert response.status_code == 200
    result = response.json()
    assert result["mean_confidence"] == 80
    assert "20.0%" in result["text"]
    assert "forecast_precipitation" in result["contributing_features"]
    assert "not physical causality" in result["caveat"]


def test_variable_trend_endpoint(client):
    route = "/api/v1/forecast/2026-09-12/variables/trend"
    response = client.get(route, params={"field": "forecast_temperature_2m"})
    assert response.status_code == 200
    assert len(response.json()["days"]) == 10
    assert all(day["value"] == 300 for day in response.json()["days"])
    assert client.get(route, params={"field": "reference_precipitation"}).status_code == 422


def test_analogs_endpoint(client, monkeypatch):
    def retrieve(selected, limit):
        assert selected["latitude"] == 22
        assert limit == 3
        return {"initialization_time": selected["initialization_time"], "latitude": 22, "longitude": 78,
                "lead_day": 1, "number_of_analogs": 0, "percentage_busted": None,
                "mean_historical_absolute_error": None, "analogs": [], "provenance": "historical fixture"}
    monkeypatch.setattr(client.app.state.analogs, "retrieve", retrieve)
    response = client.get("/api/v1/forecast/2026-09-12/cell/analogs",
                          params={"latitude": 22, "longitude": 78, "lead_day": 1, "limit": 3})
    assert response.status_code == 200
    assert response.json()["number_of_analogs"] == 0
    assert client.get("/api/v1/forecast/2026-09-12/cell/analogs",
                      params={"latitude": 22.1, "longitude": 78, "lead_day": 1}).status_code == 404


def test_new_operational_endpoints_do_not_expose_reference(client):
    forbidden = {"reference_precipitation", "forecast_error", "absolute_error", "is_bust"}
    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for nested in value.values():
                check(nested)
        elif isinstance(value, list):
            for nested in value:
                check(nested)
    for path in ("/api/v1/forecast/2026-09-12/day/1/brief",
                 "/api/v1/forecast/2026-09-12/variables/trend?field=forecast_precipitation",
                 "/api/v1/compare?current_initialization=2026-09-12&previous_initialization=2026-09-11&lead_day=1"):
        response = client.get(path)
        assert response.status_code == 200
        check(response.json())

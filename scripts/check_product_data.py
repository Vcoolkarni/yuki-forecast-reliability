"""Read-only end-to-end checks against the existing local model and forecast files."""

from fastapi.testclient import TestClient

from forecast_bust.api.app import create_app


def get(client, path, **params):
    response = client.get(path, params=params or None)
    response.raise_for_status()
    return response.json()


def main():
    with TestClient(create_app()) as client:
        health = get(client, "/health")
        assert health["status"] == "ready" and len(health["available_initializations"]) >= 2
        first, previous, latest = health["available_initializations"][0], *health["available_initializations"][-2:]
        checked = 0
        for initialization in (first, latest):
            base = f"/api/v1/forecast/{initialization}"
            summary = get(client, base + "/summary")
            timeline = get(client, base + "/timeline")
            assert len(summary["lead_day_summaries"]) == len(timeline["days"]) == 10
            assert len(get(client, base + "/variables/trend", field="forecast_temperature_2m")["days"]) == 10
            for lead in (1, 5, 10):
                records = get(client, base + f"/day/{lead}")["records"]
                assert len(records) == 289 and all(row["lead_day"] == lead for row in records)
                assert all(abs(row["confidence_score"] - 100 * (1 - row["bust_probability"])) < 1e-8 for row in records)
                assert not any("reference_precipitation" in row or "forecast_error" in row or "absolute_error" in row for row in records)
                hotspots = get(client, base + f"/day/{lead}/hotspots")["hotspots"]
                assert summary["lead_day_summaries"][lead - 1]["hotspot_count"] == len(hotspots)
                available = {(row["latitude"], row["longitude"]) for row in records}
                for hotspot in hotspots:
                    assert len(hotspot["member_cells"]) == hotspot["number_of_cells"]
                    assert {(item["latitude"], item["longitude"]) for item in hotspot["member_cells"]} <= available
                highest = get(client, base + f"/day/{lead}/highest-risk")
                assert highest["bust_probability"] == max(row["bust_probability"] for row in records)
                selected = get(client, base + "/cell", latitude=highest["latitude"], longitude=highest["longitude"], lead_day=lead)
                assert selected["explanations"] and selected["explanation_summary"]
                brief = get(client, base + f"/day/{lead}/brief")
                assert brief["lead_day"] == lead and brief["hotspot_count"] == len(hotspots)
                checked += 1
        analog = get(client, f"/api/v1/forecast/{latest}/cell/analogs",
                     latitude=selected["latitude"], longitude=selected["longitude"], lead_day=10)
        assert analog["number_of_analogs"] == len(analog["analogs"])
        assert all(item["initialization_time"] != latest for item in analog["analogs"])
        assert [item["distance"] for item in analog["analogs"]] == sorted(item["distance"] for item in analog["analogs"])
        comparison = get(client, "/api/v1/compare", current_initialization=latest,
                         previous_initialization=previous, lead_day=5)
        assert comparison["number_of_cells"] == len(comparison["cells"]) == 289
        assert all(abs(item["delta_bust_probability"] -
                       (item["current_bust_probability"] - item["previous_bust_probability"])) < 1e-10
                   for item in comparison["cells"])
        assert all(abs(item["delta_confidence"] -
                       (item["current_confidence"] - item["previous_confidence"])) < 1e-8
                   for item in comparison["cells"])
        assert sum(item["state"] == "emerging" for item in comparison["cells"]) == comparison["emerging_bust_cells"]
        assert sum(item["state"] == "resolved" for item in comparison["cells"]) == comparison["resolved_bust_cells"]
        assert sum(item["state"] == "persistent" for item in comparison["cells"]) == comparison["persistent_bust_cells"]
        assert comparison["hotspot_count_delta"] == comparison["current_hotspot_count"] - comparison["previous_hotspot_count"]
        assert all(item["delta_bust_probability"] > 0 for item in comparison["largest_risk_increases"])
        assert all(item["delta_bust_probability"] < 0 for item in comparison["largest_risk_decreases"])
        assert client.get(f"/api/v1/forecast/{latest}/day/0").status_code == 422
        assert client.get("/api/v1/forecast/not-a-date/summary").status_code == 422
        assert client.get(f"/api/v1/forecast/{latest}/cell", params={"latitude": 21.11,
                           "longitude": 78, "lead_day": 5}).status_code == 404
        print(f"PRODUCT_DATA_QA=PASS INITIALIZATIONS=2 LEADS_CHECKED={checked} GRID_CELLS_PER_DAY=289")
        print(f"ANALOGS={analog['number_of_analogs']} COMPARISON_CELLS={comparison['number_of_cells']}")


if __name__ == "__main__":
    main()

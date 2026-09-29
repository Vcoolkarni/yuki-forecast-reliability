import json
from forecast_bust.acquisition import write_era5_request


def test_era5_plan_is_bounded_and_not_submitted(tmp_path):
    cfg = {
        "geography": {"north": 24, "west": 76, "south": 20, "east": 80},
        "time": {"start_date": "2025-07-01", "end_date": "2025-07-02"},
    }
    path = write_era5_request(cfg, tmp_path / "request.json")
    content = json.loads(path.read_text())
    assert content["request"]["year"] == ["2025"]
    assert content["request"]["month"] == ["07"]
    assert content["request"]["day"] == ["01", "02"]
    assert content["request"]["area"] == [24, 76, 20, 80]

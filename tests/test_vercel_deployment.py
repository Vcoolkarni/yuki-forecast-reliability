"""Guard the public Vercel routing and artifact-bearing API entrypoint."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_vercel_services_route_api_before_spa():
    config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    services = config["services"]
    assert services["frontend"]["root"] == "frontend"
    assert services["frontend"]["framework"] == "vite"
    assert services["frontend"]["rewrites"] == [
        {"source": "/(.*)", "destination": "/index.html"}
    ]
    assert services["yuki-site"]["root"] == "."
    assert services["yuki-site"]["framework"] == "fastapi"
    assert services["yuki-site"]["entrypoint"] == "main:app"
    assert services["yuki-site"]["installCommand"] == "pip install -r requirements-web.txt"
    bundle = services["yuki-site"]["functions"]["main.py"]
    assert bundle["includeFiles"] == "{config/**,models/**,runtime/**,frontend/public/data/india-states.geojson}"
    assert "frontend/public/data/india-states.geojson" not in bundle["excludeFiles"]
    assert config["rewrites"][0] == {
        "source": "/api/(.*)", "destination": {"service": "yuki-site"}
    }
    assert config["rewrites"][-1] == {
        "source": "/(.*)", "destination": {"service": "frontend"}
    }
    assert (ROOT / "runtime/current/latest.json").is_file()
    assert (ROOT / "models/v2/recommended_0p50/bust_classifier.joblib").is_file()
    assert (ROOT / "runtime/analogs_v2/manifest.json").is_file()
    assert (ROOT / "frontend/public/data/india-states.geojson").is_file()


def test_vercel_entrypoint_reuses_existing_app():
    from main import app
    from forecast_bust.api.app import app as existing_app

    assert app is existing_app

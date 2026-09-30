"""Render deployment must stay free-tier, CPU-only, and forecast-only."""

from pathlib import Path
from collections import OrderedDict
from threading import RLock
import json
import shutil

import pytest
import yaml

from forecast_bust.api.app import create_app
from forecast_bust.api.settings import APISettings
from forecast_bust.api.v2_analogs import V2AnalogRepository
from forecast_bust.api.v2_repository import V2Repository, frozen_selection_digests


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_is_free_and_does_not_publish_forecasts_on_startup():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    services = {service["name"]: service for service in blueprint["services"]}
    assert set(services) == {"yuki-api", "yuki-site"}
    api, site = services["yuki-api"], services["yuki-site"]
    assert api["type"] == "web" and api["runtime"] == "python" and api["plan"] == "free"
    assert api["healthCheckPath"] == "/api/v2/health"
    assert "requirements-web.txt" in api["buildCommand"]
    assert "uvicorn forecast_bust.api.app:app" in api["startCommand"]
    assert site["runtime"] == "static" and site["staticPublishPath"] == "frontend/dist"
    assert {"type": "rewrite", "source": "/*", "destination": "/index.html"} in site["routes"]
    assert all(service["type"] != "cron" for service in services.values())


def test_render_serving_dependencies_are_cpu_only():
    requirements = (ROOT / "requirements-web.txt").read_text(encoding="utf-8").splitlines()
    assert "xgboost-cpu==3.4.1" in requirements
    assert not any(line.startswith("xgboost==") for line in requirements)
    assert not any("nvidia" in line.lower() for line in requirements)


def test_render_cache_limits_are_configurable_without_changing_defaults(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("FORECAST_BUST_CORS_ORIGINS", "https://example.test")
    monkeypatch.setenv("FORECAST_BUST_V2_CACHE_SIZE", "1")
    monkeypatch.setenv("FORECAST_BUST_V2_ANALOG_INDEX_CACHE_SIZE", "1")
    app = create_app(settings=APISettings.load())
    assert app.state.v2_repository.cache_size == 1
    assert V2AnalogRepository(ROOT, index_cache_size=1).index_cache_size == 1
    with pytest.raises(ValueError, match="positive"):
        V2AnalogRepository(ROOT, index_cache_size=0)


def test_one_entry_forecast_cache_evicts_before_building_next_run():
    first, second = "2024-09-26T00:00:00Z", "2024-09-29T00:00:00Z"
    repository = object.__new__(V2Repository)
    repository.lock = RLock()
    repository.cache_size = 1
    repository.cache = OrderedDict({first: {"initialization_time": first}})
    repository.frames = {second: object()}
    repository.current_runs = {}
    repository.demo_predictions = {}

    class Model:
        def predict_initialization(self, frame):
            assert not repository.cache  # Old full-grid run is gone before allocation.
            return {"initialization_time": second}

    repository.service = Model()
    assert repository.get(second)["initialization_time"] == second
    assert list(repository.cache) == [second]


def test_current_run_integrity_accepts_only_git_line_ending_conversion(tmp_path):
    packaged = ROOT / "runtime/current/runs/2026092912"
    if not packaged.is_dir():
        pytest.skip("Packaged current run is required")
    manifest = json.loads((packaged / "manifest.json").read_text(encoding="utf-8"))
    frozen = ROOT / "models/v2/recommended_0p50/frozen_selection.json"
    linux_bytes = frozen.read_bytes().replace(b"\r\n", b"\n")
    target = tmp_path / "models/v2/recommended_0p50/frozen_selection.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(linux_bytes)
    assert manifest["frozen_model_selection_sha256"] in frozen_selection_digests(target)
    target.write_bytes(linux_bytes + b"tampered")
    assert manifest["frozen_model_selection_sha256"] not in frozen_selection_digests(target)
    target.write_bytes(linux_bytes)
    run = tmp_path / "runtime/current/runs/2026092912"
    run.mkdir(parents=True)
    for name in ("manifest.json", "features.csv.gz", "predictions.json.gz"):
        shutil.copyfile(packaged / name, run / name)
    repository = V2Repository(tmp_path)
    model = type("FrozenModel", (), {"model_id": manifest["model_id"],
                                     "features": manifest["feature_names_ordered"]})()
    assert "2026-09-29T12:00:00Z" in repository._scan_current_runs(model)


def test_packaged_demo_predictions_match_frozen_source_and_require_no_model_rerun(monkeypatch):
    repository = V2Repository(ROOT, cache_size=1)
    repository.initialize()
    if not repository.demo_predictions:
        pytest.skip("Packaged demo predictions have not been generated")
    key = sorted(repository.demo_predictions)[0]
    assert len(repository.demo_predictions) == 2
    assert len(repository.frames[key]) == 38430
    monkeypatch.setattr(repository.service, "predict_initialization",
                        lambda _: pytest.fail("Packaged demo must not rerun the model"))
    artifact = repository.get(key)
    assert artifact["initialization_time"] == key
    assert len(artifact["records"]) == 38430
    assert set(artifact["records"][0]).isdisjoint(
        {"reference_precipitation", "forecast_error", "absolute_error", "is_bust"})

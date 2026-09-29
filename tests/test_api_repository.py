from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from forecast_bust.api.repository import ForecastRepository, normalize_initialization
from forecast_bust.api.settings import APISettings


def test_initialization_normalization():
    assert normalize_initialization("2026-09-12") == "2026-09-12T00:00:00Z"
    assert normalize_initialization("2026-09-12T05:30:00+05:30") == "2026-09-12T00:00:00Z"
    with pytest.raises(ValueError, match="ISO"):
        normalize_initialization("not-a-date")


def test_cache_reuses_inference_concurrently_and_evicts(monkeypatch):
    settings = APISettings(Path("model"), Path("forecast"), Path("config"), 1, ())
    frame = pd.DataFrame({"initialization_time": ["2026-09-11", "2026-09-12"]})
    calls = []
    service = SimpleNamespace(model_id="test", threshold=0.2, bundle={"features": ["lead_day"]})

    def predict(data):
        calls.append(data.initialization_time.iloc[0])
        return {"initialization_time": normalize_initialization(calls[-1])}

    service.predict_initialization = predict
    monkeypatch.setattr("forecast_bust.api.repository.ForecastInference.from_artifact", lambda *args: service)
    monkeypatch.setattr("forecast_bust.api.repository.pd.read_csv", lambda *args: frame)
    store = ForecastRepository(settings)
    store.initialize()
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(store.get, ["2026-09-12"] * 8))
    assert len(calls) == 1
    assert all(value == outputs[0] for value in outputs)
    assert store.health()["cached_initializations"] == 1
    store.get("2026-09-11")
    store.get("2026-09-12")
    assert len(calls) == 3
    with pytest.raises(KeyError):
        store.get("2026-01-01")


def test_repository_rejects_reference_source(monkeypatch):
    settings = APISettings(Path("model"), Path("forecast"), Path("config"), 1, ())
    monkeypatch.setattr("forecast_bust.api.repository.ForecastInference.from_artifact", lambda *args: object())
    monkeypatch.setattr("forecast_bust.api.repository.pd.read_csv", lambda *args: pd.DataFrame({
        "initialization_time": ["2026-09-12"], "reference_precipitation": [1.0]}))
    store = ForecastRepository(settings)
    with pytest.raises(ValueError, match="training/reference"):
        store.initialize()
    assert store.health()["status"] == "not_ready"

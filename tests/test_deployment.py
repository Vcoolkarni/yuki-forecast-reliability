"""Checks for the deployment bundle and immutable current-run handoff."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import pandas as pd
import pytest

from forecast_bust.api.settings import APISettings
from forecast_bust.api.v2_analogs import V2AnalogRepository
from forecast_bust.v2.current_store import CurrentObjectStore


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_analogs_match_original_training_lookup():
    packaged = ROOT / "runtime/analogs_v2/day_01.npz"
    original = ROOT / "data/processed/v2/recommended_0p50/train"
    if not packaged.is_file() or not original.is_dir():
        pytest.skip("Local source and runtime analog index are required for equivalence check")
    source = pd.read_csv(next(original.glob("*.csv.gz")), nrows=1)
    current = {"initialization_time": "2024-09-01T00:00:00Z", "lead_day": 1,
               "latitude": float(source.latitude.iloc[0]), "longitude": float(source.longitude.iloc[0]),
               "forecast_precipitation": float(source.forecast_precipitation.iloc[0]),
               "forecast_precipitable_water": float(source.forecast_precipitable_water.iloc[0]),
               "forecast_cape_surface": float(source.forecast_cape_surface.iloc[0]),
               "gefs_precipitation_mean_mm": float(source.gefs_precipitation_mean_mm.iloc[0]),
               "gefs_end_window_spread_6h_mm": float(source.gefs_end_window_spread_6h_mm.iloc[0])}
    a = V2AnalogRepository(ROOT / "runtime/analogs_v2").retrieve(current)
    b = V2AnalogRepository(ROOT / "data/processed/v2/recommended_0p50").retrieve(current)
    assert a == b
    assert all(2021 <= int(item["initialization_time"][:4]) <= 2023 for item in a["analogs"])


def test_production_cors_requires_explicit_origin(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("FORECAST_BUST_CORS_ORIGINS", raising=False)
    with pytest.raises(ValueError, match="FORECAST_BUST_CORS_ORIGINS"):
        APISettings.load()
    monkeypatch.setenv("FORECAST_BUST_CORS_ORIGINS", "https://example.test")
    assert APISettings.load().cors_origins == ("https://example.test",)


class MemoryObjectClient:
    def __init__(self):
        self.objects = {}
        self.metadata = {}
        self.fail_name = None

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            error = OSError("not found")
            error.response = {"Error": {"Code": "404"}}
            raise error
        return {"Metadata": self.metadata[(Bucket, Key)]}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        if self.fail_name and key.endswith(self.fail_name):
            raise OSError("simulated interrupted transfer")
        self.objects[(bucket, key)] = Path(filename).read_bytes()
        self.metadata[(bucket, key)] = ExtraArgs["Metadata"]

    def put_object(self, *, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[(bucket, key)])


def test_object_store_commits_pointer_only_after_valid_artifacts(tmp_path):
    store = object.__new__(CurrentObjectStore)
    store.bucket = "test-bucket"
    store.prefix = "test/current"
    store.client = MemoryObjectClient()
    source = tmp_path / "source"
    run = source / "runs/2026092912"
    run.mkdir(parents=True)
    artifacts = {}
    for name, payload in (("features.csv.gz", b"feature"), ("predictions.json.gz", b"prediction")):
        (run / name).write_bytes(payload)
        artifacts[name] = {"sha256": sha256(payload).hexdigest(), "bytes": len(payload)}
    (run / "manifest.json").write_text(json.dumps({"status": "complete", "run_id": "2026092912",
                                                    "artifacts": artifacts}), encoding="utf-8")
    store.client.fail_name = "predictions.json.gz"
    with pytest.raises(OSError):
        store.publish(source, "2026092912")
    assert (store.bucket, store._key("latest.json")) not in store.client.objects
    store.client.fail_name = None
    store.publish(source, "2026092912")
    store.publish(source, "2026092912")  # Idempotent retry does not overwrite immutable objects.
    pointer_before = store.client.objects[(store.bucket, store._key("latest.json"))]
    store.client.metadata[(store.bucket, store._key("runs/2026092912/features.csv.gz"))] = {"sha256": "different"}
    with pytest.raises(ValueError, match="immutable"):
        store.publish(source, "2026092912")
    assert store.client.objects[(store.bucket, store._key("latest.json"))] == pointer_before
    target = tmp_path / "mirror"
    assert store.sync_latest(target) == "2026092912"
    assert (target / "runs/2026092912/predictions.json.gz").read_bytes() == b"prediction"
    assert (target / "latest.json").is_file()

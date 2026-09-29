from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import numpy as np
import pandas as pd

import pytest

from forecast_bust.acquisition import GribMessage
from forecast_bust.v2.budget_planning import load_budget_config
from forecast_bust.v2.byte_budget import ByteBudget, DownloadLimitReached
from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.recommended_acquisition import (era5_month_jobs, jobs_for_date,
                                                       recommended_dates, split_for_date)
from forecast_bust.v2.recommended_dataset import recommended_forecast_config
from forecast_bust.v2.feature_schema import forecast_feature_schema
from forecast_bust.v2.dataset import TARGETS
from forecast_bust.v2.dataset import BASE_FORECAST, validate_historical


def test_recommended_jobs_and_final_test_partition(tmp_path):
    base, budget = load_v2_config(), load_budget_config()
    dates = recommended_dates(base, budget)
    assert len(dates) == 175
    assert [sum(day.startswith(str(year)) for day in dates) for year in range(2021, 2026)] == [35] * 5
    assert split_for_date("2025-09-29") == "final_test_untouched"
    for day in (dates[0], dates[-1]):
        jobs = jobs_for_date(base, budget, day, tmp_path / "recommended")
        assert len(jobs) == 160
        assert sum(job.source == "gfs" for job in jobs) == 110
        assert sum(job.variable == "precipitation" for job in jobs) == 40
        assert sum(job.variable == "precipitation_mean_6h" for job in jobs) == 40
        assert sum(job.variable == "precipitation_spread_6h" for job in jobs) == 10
        assert all("0p50" in job.url for job in jobs)
        assert all(job.target.is_relative_to(tmp_path / "recommended" / split_for_date(day)) for job in jobs)
        assert sorted(job.forecast_hour for job in jobs if job.variable == "precipitation" and job.forecast_hour <= 24) == [6, 12, 18, 24]
        assert sorted(job.forecast_hour for job in jobs if job.variable == "precipitation" and job.forecast_hour > 216) == [222, 228, 234, 240]
    months = era5_month_jobs(base, dates, tmp_path / "recommended")
    assert len(months) == 25
    assert all(item["target"].is_relative_to(tmp_path / "recommended" / "final_test_untouched")
               for item in months if item["month"].startswith("2025"))
    assert months[-1]["month"] == "202510"


def test_recommended_feature_contract_excludes_targets_and_daily_spread():
    config = recommended_forecast_config(load_v2_config(), load_budget_config())
    features = set(forecast_feature_schema(config))
    assert not features & TARGETS
    assert "day_of_year" not in features
    assert "gefs_precipitation_mean_mm" in features
    assert "gefs_end_window_spread_6h_mm" in features
    assert "gefs_precipitation_std_mm" not in features
    assert config["geography"]["grid_resolution_degrees"] == .5


def test_training_rejects_test_year_in_training_manifest(tmp_path):
    from forecast_bust.v2.recommended_training import train_recommended

    data_root = tmp_path / "processed"
    data_root.mkdir()
    (data_root / "dataset_manifest.json").write_text(json.dumps({
        "initializations": {"train": 105, "validation": 35, "final_test_untouched": 35},
        "dates": {"train": ["2025-06-01"], "validation": ["2024-06-01"],
                  "final_test_untouched": ["2025-06-04"]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="approved years"):
        train_recommended(load_v2_config(), load_budget_config(),
                          data_root=data_root, model_root=tmp_path / "models",
                          report_root=tmp_path / "reports")


def test_era5_float32_csv_roundtrip_preserves_error_consistency(tmp_path):
    reference = np.float32(159.29269409179688)
    forecast = 15.3125
    record = {"initialization_time": "2021-06-01T00:00:00Z",
              "valid_time": "2021-06-02T00:00:00Z", "latitude": 20.0,
              "longitude": 76.0, "lead_day": 1,
              "reference_precipitation": reference,
              "forecast_error": forecast - reference,
              "absolute_error": abs(forecast - reference),
              "target_absolute_error_mm": abs(forecast - reference)}
    record.update({name: 1.0 for name in BASE_FORECAST})
    record["forecast_precipitation"] = forecast
    path = tmp_path / "partition.csv.gz"
    pd.DataFrame([record]).to_csv(path, index=False, compression="gzip")
    restored = pd.read_csv(path, dtype={"reference_precipitation": "float32"})
    assert restored.reference_precipitation.dtype == np.float32
    validate_historical(restored, [])


def test_byte_budget_persists_hard_cap_and_counts_retries(tmp_path):
    root = tmp_path / "cache"
    with ByteBudget(root, 16, "profile") as meter:
        meter.reserve_transfer(12)
        meter.consume(6)
        assert meter.downloaded_bytes == 6 and meter.charged_bytes == 12
        with pytest.raises(DownloadLimitReached):
            meter.reserve_transfer(5)
    with ByteBudget(root, 16, "profile") as meter:
        assert meter.downloaded_bytes == 6 and meter.charged_bytes == 12
        meter.reserve_transfer(4)  # A retry must consume remaining budget.
        meter.consume(4)
        with pytest.raises(DownloadLimitReached):
            meter.reserve_transfer(1)
    with pytest.raises(ValueError, match="different profile"):
        ByteBudget(root, 16, "changed-profile")


def test_byte_budget_is_safe_for_bounded_parallel_transfers(tmp_path):
    with ByteBudget(tmp_path / "cache", 1000, "parallel") as meter:
        def transfer(_):
            meter.reserve_transfer(10)
            meter.consume(10)

        with ThreadPoolExecutor(max_workers=48) as pool:
            list(pool.map(transfer, range(100)))
        assert meter.downloaded_bytes == meter.charged_bytes == 1000
        with pytest.raises(DownloadLimitReached):
            meter.reserve_transfer(1)


def test_grib_transfer_reserves_exact_range_and_cache_skips(monkeypatch, tmp_path):
    import forecast_bust.v2.acquisition as acquisition
    from forecast_bust.v2.planning import MessageJob

    payload = b"GRIBABCD7777"
    target = tmp_path / "cache" / "sample.grb2"
    job = MessageJob("gefs", "2022-07-01", 24, "precipitation_mean_6h",
                     "https://example.org/geavg", ":APCP:surface:", target,
                     accumulation_start_hour=18)
    monkeypatch.setattr(acquisition, "_inspect_message",
                        lambda *_: GribMessage(100, 111, "APCP:surface:18-24 hour acc fcst:ens mean"))
    calls = []

    class Response:
        status_code = 206
        headers = {"Content-Range": "bytes 100-111/1000"}
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def raise_for_status(self): return None
        def iter_content(self, chunk_size): yield payload

    def fake_get(*_args, **_kwargs):
        calls.append(True)
        return Response()

    monkeypatch.setattr(acquisition.requests, "get", fake_get)
    with ByteBudget(tmp_path / "cache", 12, "test") as meter:
        assert acquisition.download_message(job, budget=meter) == target
        assert meter.downloaded_bytes == meter.charged_bytes == 12
        assert acquisition.download_message(job, budget=meter) == target
        assert len(calls) == 1
    assert target.read_bytes() == payload


def test_grib_connection_reset_resumes_partial_and_charges_retry(monkeypatch, tmp_path):
    import requests
    import forecast_bust.v2.acquisition as acquisition
    from forecast_bust.v2.planning import MessageJob

    target = tmp_path / "cache" / "sample.grb2"
    job = MessageJob("gefs", "2022-07-01", 24, "precipitation_mean_6h",
                     "https://example.org/geavg", ":APCP:surface:", target,
                     accumulation_start_hour=18)
    monkeypatch.setattr(acquisition, "_inspect_message",
                        lambda *_: GribMessage(100, 111, "APCP:surface:18-24 hour acc fcst:ens mean"))
    monkeypatch.setattr(acquisition, "_retry_delay", lambda *_: None)
    ranges = []

    class Response:
        status_code = 206
        def __init__(self, start):
            self.start = start
            self.headers = {"Content-Range": f"bytes {start}-111/1000"}
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def raise_for_status(self): return None
        def iter_content(self, chunk_size):
            if self.start == 100:
                yield b"GRIB"
                raise requests.exceptions.ConnectionError("connection reset")
            yield b"ABCD7777"

    def fake_get(*_args, **kwargs):
        value = int(kwargs["headers"]["Range"].split("=")[1].split("-")[0])
        ranges.append(value)
        return Response(value)

    monkeypatch.setattr(acquisition.requests, "get", fake_get)
    with ByteBudget(tmp_path / "cache", 20, "retry-test") as meter:
        assert acquisition.download_message(job, budget=meter) == target
        assert meter.downloaded_bytes == 12
        assert meter.charged_bytes == 20
    assert target.read_bytes() == b"GRIBABCD7777"
    assert ranges == [100, 104]


def test_grib_retries_transient_inventory_http_error_only(monkeypatch, tmp_path):
    import requests
    import forecast_bust.v2.acquisition as acquisition
    from forecast_bust.v2.planning import MessageJob

    target = tmp_path / "cache" / "sample.grb2"
    job = MessageJob("gefs", "2022-07-01", 24, "precipitation_mean_6h",
                     "https://example.org/geavg", ":APCP:surface:", target,
                     accumulation_start_hour=18)
    attempts = []
    monkeypatch.setattr(acquisition, "_retry_delay", lambda *_: None)

    def inspect(*_):
        attempts.append(True)
        if len(attempts) == 1:
            response = requests.Response()
            response.status_code = 503
            raise requests.exceptions.HTTPError(response=response)
        return GribMessage(100, 111, "APCP:surface:18-24 hour acc fcst:ens mean")

    class Response:
        status_code = 206
        headers = {"Content-Range": "bytes 100-111/1000"}
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def raise_for_status(self): return None
        def iter_content(self, chunk_size): yield b"GRIBABCD7777"

    monkeypatch.setattr(acquisition, "_inspect_message", inspect)
    monkeypatch.setattr(acquisition.requests, "get", lambda *_args, **_kwargs: Response())
    with ByteBudget(tmp_path / "cache", 12, "inventory-retry-test") as meter:
        acquisition.download_message(job, budget=meter)
    assert len(attempts) == 2


def test_transient_failure_set_is_bounded_to_transport_and_retryable_statuses():
    import requests
    from forecast_bust.v2.acquisition import _transient

    for error in (requests.exceptions.ConnectionError(), ConnectionResetError(),
                  requests.exceptions.ConnectTimeout(), requests.exceptions.ReadTimeout()):
        assert _transient(error)
    for status in (429, 500, 502, 503, 504):
        response = requests.Response()
        response.status_code = status
        assert _transient(requests.exceptions.HTTPError(response=response))
    for status in (400, 403, 404):
        response = requests.Response()
        response.status_code = status
        assert not _transient(requests.exceptions.HTTPError(response=response))


def test_era5_content_length_rejected_before_transfer(monkeypatch, tmp_path):
    import cdsapi
    import forecast_bust.v2.recommended_acquisition as acquisition

    base = deepcopy(load_v2_config())
    base["geography"].update({"south": 20.0, "north": 20.5, "west": 76.0, "east": 76.5})
    job = {"month": "202207", "request_dates": ["2022-07-02"],
           "required_hours": [], "target": tmp_path / "cache" / "era5_tp_202207.nc",
           "request_path": tmp_path / "cache" / "requests" / "plan.json"}
    monkeypatch.setattr(acquisition, "load_cds_credentials", lambda *_: ("https://example.org", "not-real"))

    class Result:
        content_length = 17

    class Client:
        def __init__(self, **_): pass
        def retrieve(self, *_): return Result()

    monkeypatch.setattr(cdsapi, "Client", Client)
    with ByteBudget(tmp_path / "cache", 16, "test") as meter:
        with pytest.raises(DownloadLimitReached):
            acquisition.download_era5_month(job, base, meter, Path("unused"))
        assert meter.downloaded_bytes == meter.charged_bytes == 0


def test_era5_results_stream_is_metered_and_cached(monkeypatch, tmp_path):
    import cdsapi
    import forecast_bust.v2.recommended_acquisition as acquisition

    base = deepcopy(load_v2_config())
    base["geography"].update({"south": 20.0, "north": 20.5, "west": 76.0, "east": 76.5})
    target = tmp_path / "cache" / "era5_tp_202207.nc"
    job = {"month": "202207", "request_dates": ["2022-07-02"],
           "required_hours": [], "target": target,
           "request_path": tmp_path / "cache" / "requests" / "plan.json"}
    payload = b"era5-smoke-payload"
    calls = []
    monkeypatch.setattr(acquisition, "load_cds_credentials", lambda *_: ("https://example.org", "not-real"))
    monkeypatch.setattr(acquisition, "_validate_era5", lambda *_: None)

    class Response:
        status_code = 200
        headers = {"ETag": '"same"'}
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def raise_for_status(self): return None
        def iter_content(self, chunk_size): yield payload

    class Session:
        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    class Result:
        content_length = len(payload)
        location = "https://example.org/result.nc"
        request_options = {"timeout": 60, "verify": True}
        session = Session()

    class Client:
        def __init__(self, **_): pass
        def retrieve(self, *_): return Result()

    monkeypatch.setattr(cdsapi, "Client", Client)
    with ByteBudget(tmp_path / "cache", len(payload), "test") as meter:
        assert acquisition.download_era5_month(job, base, meter, Path("unused"))
        assert meter.downloaded_bytes == meter.charged_bytes == len(payload)
        assert not acquisition.download_era5_month(job, base, meter, Path("unused"))
    assert target.read_bytes() == payload
    assert calls == [(Result.location, {"headers": {"Accept-Encoding": "identity"},
                                      "stream": True, "timeout": 60, "verify": True})]

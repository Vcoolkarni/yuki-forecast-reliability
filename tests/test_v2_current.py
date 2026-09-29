"""Current-run planning and fail-closed discovery; no network or evaluation data."""

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json

import pytest
import yaml

from forecast_bust.v2.balanced import component_hours
from forecast_bust.v2.current import (candidate_initializations, check_complete,
                                      discover_latest_complete, jobs_for_initialization,
                                      publish_current_run)
from forecast_bust.api.v2_repository import V2Repository

ROOT = Path(__file__).resolve().parents[1]
BASE = yaml.safe_load((ROOT / "config/v2.yaml").read_text(encoding="utf-8"))
BUDGET = yaml.safe_load((ROOT / "config/v2_budget_profiles.yaml").read_text(encoding="utf-8"))


def test_live_jobs_preserve_exact_frozen_product_and_precipitation_windows(tmp_path):
    initialization = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    jobs = jobs_for_initialization(BASE, BUDGET, initialization, tmp_path)
    assert len(jobs) == 160
    assert sum(job.source == "gfs" for job in jobs) == 110
    assert sum(job.variable == "precipitation_mean_6h" for job in jobs) == 40
    assert sum(job.variable == "precipitation_spread_6h" for job in jobs) == 10
    assert all("/12/atmos/" in job.url and ".t12z." in job.url for job in jobs)
    assert all("0p50" in job.url for job in jobs)
    for lead in (1, 5, 10):
        hours = component_hours(lead)
        for variable in ("precipitation", "precipitation_mean_6h"):
            selected = [job for job in jobs if job.variable == variable and job.forecast_hour in hours]
            assert [job.forecast_hour for job in selected] == hours
            assert [(job.accumulation_start_hour, job.forecast_hour) for job in selected] == [
                (hour - 6, hour) for hour in hours]
        spread = [job for job in jobs if job.variable == "precipitation_spread_6h" and
                  job.forecast_hour == lead * 24]
        assert len(spread) == 1 and spread[0].accumulation_start_hour == lead * 24 - 6


def test_latest_incomplete_cycle_falls_back_only_after_all_required_inventory_checks(tmp_path):
    checked = []
    def inspector(job):
        checked.append(job)
        if "/18/atmos/" in job.url:
            raise FileNotFoundError("f240 has not been published")
    initialization, jobs, report = discover_latest_complete(BASE, BUDGET, tmp_path,
        datetime(2026, 9, 29, 18, 8, tzinfo=timezone.utc), cycles=2, inspector=inspector)
    assert initialization.hour == 12
    assert len(jobs) == 160
    assert report["fallback_required"] is True
    assert report["candidates"][0]["complete"] is False
    assert report["candidates"][1]["checked_messages"] == 160
    assert len(checked) == 161
    assert checked[0].forecast_hour == 240


def test_incomplete_selected_cycle_is_never_accepted(tmp_path):
    status = check_complete(jobs_for_initialization(BASE, BUDGET,
        datetime(2026, 9, 29, 12, tzinfo=timezone.utc), tmp_path),
        inspector=lambda job: (_ for _ in ()).throw(ValueError("missing APCP")) if
            job.variable == "precipitation_spread_6h" else None)
    assert not status["complete"]
    assert status["failure_type"] == "ValueError"
    with pytest.raises(RuntimeError, match="No complete GFS\\+GEFS"):
        discover_latest_complete(BASE, BUDGET, tmp_path,
            datetime(2026, 9, 29, 12, tzinfo=timezone.utc), cycles=1,
            inspector=lambda job: (_ for _ in ()).throw(FileNotFoundError("missing")))


def test_candidate_cycle_uses_utc_not_local_time():
    candidates = candidate_initializations(datetime(2026, 9, 30, 0, 5,
        tzinfo=timezone.utc), 3)
    assert [(value.day, value.hour) for value in candidates] == [(30, 0), (29, 18), (29, 12)]


def test_demo_and_current_runs_cannot_be_compared(tmp_path):
    store = V2Repository(tmp_path)
    demo = "2024-09-29T00:00:00Z"
    first = "2026-09-29T06:00:00Z"
    second = "2026-09-29T12:00:00Z"
    store.frames = {demo: object()}
    store.current_runs = {first: {"manifest": {"model_id": "frozen", "grid": {"step": .5}}},
                          second: {"manifest": {"model_id": "frozen", "grid": {"step": .5}}}}
    assert not store.comparison_compatible(second, demo)
    assert store.comparison_compatible(second, first)
    store.current_runs[first]["manifest"]["grid"] = {"step": .25}
    assert not store.comparison_compatible(second, first)


def test_published_run_reuse_repairs_pointer_without_redownload(tmp_path, monkeypatch):
    initialization = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    folder = tmp_path / "processed/runs/2026092912"
    folder.mkdir(parents=True)
    artifacts = {}
    for name in ("features.csv.gz", "predictions.json.gz"):
        payload = name.encode()
        (folder / name).write_bytes(payload)
        artifacts[name] = {"sha256": sha256(payload).hexdigest()}
    manifest = {"status": "complete", "run_id": "2026092912",
                "initialization_utc": "2026-09-29T12:00:00Z", "artifacts": artifacts}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr("forecast_bust.v2.current.discover_latest_complete",
        lambda *args, **kwargs: (initialization, [], {"fallback_required": False}))
    settings = {"raw_dir": "raw", "processed_dir": "processed", "discovery_cycles": 2}
    assert publish_current_run(BASE, BUDGET, settings, tmp_path, printer=lambda _: None) == manifest
    pointer = json.loads((tmp_path / "processed/latest.json").read_text(encoding="utf-8"))
    assert pointer["run_id"] == "2026092912"


def test_failed_discovery_preserves_last_successful_pointer(tmp_path, monkeypatch):
    pointer = tmp_path / "processed/latest.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text('{"run_id":"2026092912"}', encoding="utf-8")
    def unavailable(*args, **kwargs):
        raise RuntimeError("NOAA run incomplete")
    monkeypatch.setattr("forecast_bust.v2.current.discover_latest_complete", unavailable)
    with pytest.raises(RuntimeError, match="incomplete"):
        publish_current_run(BASE, BUDGET, {"raw_dir": "raw", "processed_dir": "processed",
            "discovery_cycles": 1}, tmp_path, printer=lambda _: None)
    assert json.loads(pointer.read_text(encoding="utf-8"))["run_id"] == "2026092912"

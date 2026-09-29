"""Complete-run discovery and immutable, forecast-only V2 operational publishing."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import gzip
import json
import os

import pandas as pd

from .acquisition import (_inspect_message, _retry_delay, _transient, _verify_accumulation,
                          _verify_instantaneous, download_message)
from .balanced import assemble_balanced_forecast
from .byte_budget import ByteBudget
from .dataset import IDENTITY, TARGETS, validate_forecast
from .geography import validate_full_grid_coverage
from .inference import V2Inference
from .planning import MessageJob
from .recommended_acquisition import jobs_for_date
from .recommended_dataset import recommended_forecast_config

GIB = 1024 ** 3


def candidate_initializations(now: datetime, count: int) -> list[datetime]:
    if now.tzinfo is None or count < 1:
        raise ValueError("Discovery needs an aware UTC clock and a positive cycle limit")
    utc = now.astimezone(timezone.utc)
    latest = utc.replace(hour=(utc.hour // 6) * 6, minute=0, second=0, microsecond=0)
    return [latest - timedelta(hours=6 * index) for index in range(count)]


def run_id(initialization: datetime) -> str:
    return initialization.astimezone(timezone.utc).strftime("%Y%m%d%H")


def jobs_for_initialization(base: dict, budget_config: dict, initialization: datetime,
                            raw_root: Path) -> list[MessageJob]:
    if initialization.tzinfo is None:
        raise ValueError("NOAA initialization must be timezone-aware")
    utc = initialization.astimezone(timezone.utc)
    if utc.hour not in {0, 6, 12, 18} or utc.minute or utc.second or utc.microsecond:
        raise ValueError("NOAA initialization must be an exact six-hour cycle")
    return jobs_for_date(base, budget_config, utc.strftime("%Y-%m-%d"),
                         cycle=f"{utc.hour:02d}", folder=raw_root / run_id(utc))


def inspect_required_message(job: MessageJob) -> None:
    for attempt in range(1, 6):
        try:
            message = _inspect_message(job)
            _verify_accumulation(job, message.description)
            _verify_instantaneous(job, message.description)
            if message.size is None or message.size <= 0:
                raise ValueError("NOAA inventory has no bounded GRIB message length")
            return
        except Exception as error:
            if not _transient(error) or attempt == 5:
                raise
            _retry_delay(attempt)


def check_complete(jobs: list[MessageJob], inspector=inspect_required_message) -> dict:
    """Check final Day-10 sentinels first, then every exact required GRIB inventory item."""
    sentinels = [job for job in jobs if job.forecast_hour == 240 and
                 job.variable in {"precipitation", "precipitation_mean_6h", "precipitation_spread_6h"}]
    ordered = list(dict.fromkeys(sentinels + jobs))
    checked = 0
    for job in ordered:
        try:
            inspector(job)
        except Exception as error:
            return {"complete": False, "checked_messages": checked,
                    "required_messages": len(jobs), "failure_type": type(error).__name__,
                    "failure": str(error), "failed_source": job.source,
                    "failed_forecast_hour": job.forecast_hour, "failed_variable": job.variable}
        checked += 1
    return {"complete": True, "checked_messages": checked, "required_messages": len(jobs)}


def discover_latest_complete(base: dict, budget_config: dict, raw_root: Path,
                             now: datetime | None = None, cycles: int = 8,
                             inspector=inspect_required_message) -> tuple[datetime, list[MessageJob], dict]:
    observed = now or datetime.now(timezone.utc)
    candidates = []
    for initialization in candidate_initializations(observed, cycles):
        jobs = jobs_for_initialization(base, budget_config, initialization, raw_root)
        status = check_complete(jobs, inspector)
        candidates.append({"initialization_utc": initialization.isoformat().replace("+00:00", "Z"), **status})
        if status["complete"]:
            return initialization, jobs, {"discovered_at_utc": observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                                          "selected_initialization_utc": candidates[-1]["initialization_utc"],
                                          "fallback_required": len(candidates) > 1,
                                          "fallback_reason": candidates[0].get("failure") if len(candidates) > 1 else None,
                                          "candidates": candidates}
    raise RuntimeError("No complete GFS+GEFS Day 1–10 run in the bounded discovery window: " +
                       json.dumps(candidates, allow_nan=False))


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    with partial.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)


def _sha(path: Path) -> str:
    with path.open("rb") as handle:
        digest = sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_current_run(base: dict, budget_config: dict, settings: dict, project_root: Path,
                        now: datetime | None = None, printer=print,
                        inspector=inspect_required_message) -> dict:
    """Download only a complete NOAA run; publish the pointer last, after all validation."""
    raw_root = project_root / settings["raw_dir"]
    processed_root = project_root / settings["processed_dir"]
    initialization, jobs, discovery = discover_latest_complete(
        base, budget_config, raw_root, now, int(settings["discovery_cycles"]), inspector)
    identifier = run_id(initialization)
    output = processed_root / "runs" / identifier
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("status") != "complete" or manifest.get("run_id") != identifier
                or manifest.get("initialization_utc") != initialization.isoformat().replace("+00:00", "Z")):
            raise ValueError("Previously published current-run manifest is incomplete or mismatched")
        for name in ("features.csv.gz", "predictions.json.gz"):
            if _sha(output / name) != manifest["artifacts"][name]["sha256"]:
                raise ValueError("Previously published current-run artifact fails its immutable hash")
        _atomic_bytes(processed_root / "latest.json", json.dumps({"run_id": identifier,
            "manifest_sha256": _sha(manifest_path)}, indent=2).encode("utf-8"))
        printer(f"CURRENT_RUN_ALREADY_PUBLISHED={identifier}")
        return manifest
    forecast_config = recommended_forecast_config(base, budget_config)
    limit = int(float(settings["max_new_payload_gib_per_run"]) * GIB)
    profile = sha256(json.dumps({"run_id": identifier, "grid": budget_config["grid"],
        "gfs": budget_config["gfs"], "gefs": budget_config["gefs"]}, sort_keys=True).encode()).hexdigest()
    cache_bytes = sum(job.target.stat().st_size for job in jobs if job.target.is_file())
    with ByteBudget(raw_root / identifier, limit, profile) as meter:
        before = meter.downloaded_bytes
        def transfer(job: MessageJob) -> Path:
            return download_message(job, max_message_mib=16.0, budget=meter)
        with ThreadPoolExecutor(max_workers=int(settings["download_workers"])) as pool:
            list(pool.map(transfer, jobs))
        transferred = meter.downloaded_bytes - before
    printer(f"NOAA_MESSAGES_READY={len(jobs)} NEW_PAYLOAD_BYTES={transferred} CACHED_PAYLOAD_BYTES={cache_bytes}")
    forecast, components = assemble_balanced_forecast(forecast_config, initialization.strftime("%Y-%m-%d"),
        list(range(1, 11)), [job for job in jobs if job.source == "gfs"],
        [job for job in jobs if job.source == "gefs"], cycle=f"{initialization.hour:02d}")
    validate_full_grid_coverage(forecast, forecast_config["geography"])
    service = V2Inference(project_root / "models/v2/recommended_0p50", project_root / "config/inference.yaml")
    if set(forecast.columns) & TARGETS:
        raise ValueError("Current forecast unexpectedly contains reference/target columns")
    columns = list(dict.fromkeys(IDENTITY + service.features))
    forecast = validate_forecast(forecast[columns], service.features)
    if len(forecast) != 38430 or set(forecast.lead_day) != set(range(1, 11)):
        raise ValueError("Current run must contain all 3,843 grid centers for all ten leads")
    predictions = service.predict_initialization(forecast)
    if len(predictions["records"]) != len(forecast):
        raise ValueError("Frozen V2 inference did not return one prediction per grid record")
    output.mkdir(parents=True, exist_ok=True)
    features_path = output / "features.csv.gz"
    feature_part = features_path.with_suffix(features_path.suffix + ".part")
    forecast.to_csv(feature_part, index=False, compression="gzip")
    os.replace(feature_part, features_path)
    prediction_path = output / "predictions.json.gz"
    _atomic_bytes(prediction_path, gzip.compress(json.dumps(predictions, allow_nan=False,
        separators=(",", ":")).encode("utf-8")))
    frozen_path = project_root / "models/v2/recommended_0p50/frozen_selection.json"
    manifest = {"run_id": identifier, "run_kind": "current_forecast", "status": "complete",
        "initialization_utc": initialization.isoformat().replace("+00:00", "Z"),
        "acquired_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "valid_start_utc": (initialization + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "valid_end_utc": (initialization + timedelta(days=10)).isoformat().replace("+00:00", "Z"),
        "discovery": discovery, "source_products": {"gfs": budget_config["gfs"]["product"],
        "gefs": budget_config["gefs"]["product"], "gefs_directory": budget_config["gefs"]["directory"]},
        "source_urls": sorted({job.url for job in jobs}), "component_hours": components,
        "message_provenance": [{"source": job.source, "variable": job.variable,
            "forecast_hour": job.forecast_hour, "accumulation_start_hour": job.accumulation_start_hour,
            "provenance_path": str(job.target.with_suffix(job.target.suffix + ".provenance.json").relative_to(project_root))}
            for job in jobs], "model_id": service.model_id,
        "frozen_model_selection_sha256": _sha(frozen_path), "feature_schema_version": base["model"]["feature_schema_version"],
        "feature_names_ordered": service.features, "grid": {**forecast_config["geography"], "cells_per_lead": 3843},
        "records": len(forecast), "new_payload_bytes": transferred, "cached_payload_bytes": cache_bytes,
        "artifacts": {name: {"sha256": _sha(path), "bytes": path.stat().st_size}
                      for name, path in (("features.csv.gz", features_path), ("predictions.json.gz", prediction_path))}}
    _atomic_bytes(manifest_path, json.dumps(manifest, indent=2, allow_nan=False).encode("utf-8"))
    _atomic_bytes(processed_root / "latest.json", json.dumps({"run_id": identifier,
        "manifest_sha256": _sha(manifest_path)}, indent=2).encode("utf-8"))
    printer(f"CURRENT_RUN_PUBLISHED={identifier} RECORDS={len(forecast)} MODEL_ID={service.model_id}")
    return manifest

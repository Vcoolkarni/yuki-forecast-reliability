"""Explicit V2 acquisition primitives. Importing this module never downloads data."""

from __future__ import annotations

from hashlib import sha256
from functools import lru_cache
from pathlib import Path
import json
import os
import re
import time

import requests

from ..acquisition import GribMessage, download_era5, write_era5_request_for_dates
from .planning import MessageJob, era5_month_plan

TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_TRANSFER_ATTEMPTS = 5


def _transient(error: BaseException) -> bool:
    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        return response is not None and response.status_code in TRANSIENT_HTTP_STATUS
    return isinstance(error, (requests.exceptions.ConnectionError,
                              requests.exceptions.ConnectTimeout,
                              requests.exceptions.ReadTimeout,
                              ConnectionResetError))


def _retry_delay(attempt: int) -> None:
    time.sleep(min(2 ** (attempt - 1), 16))


def _verify_accumulation(job: MessageJob, description: str) -> None:
    if job.accumulation_start_hour is None:
        return
    match = re.search(r"(?:^|:)(\d+)-(\d+) hour acc fcst(?:$|:)", description)
    if match is None or (int(match[1]), int(match[2])) != (job.accumulation_start_hour, job.forecast_hour):
        raise ValueError(f"{job.source.upper()} precipitation interval does not match the required {job.accumulation_start_hour}–{job.forecast_hour} h window; observed inventory: {description}")
    if job.variable == "precipitation_mean_6h" and "ens mean" not in description.lower():
        raise ValueError(f"Expected published GEFS ensemble mean: {description}")
    if job.variable == "precipitation_spread_6h" and "ens std dev" not in description.lower():
        raise ValueError(f"Expected published GEFS ensemble spread: {description}")


def _verify_instantaneous(job: MessageJob, description: str) -> None:
    if job.source == "gfs" and job.accumulation_start_hour is None:
        if f":{job.forecast_hour} hour fcst:" not in f":{description}":
            raise ValueError(f"GFS forecast hour does not match f{job.forecast_hour:03d}: {description}")


@lru_cache(maxsize=256)
def _inventory_lines(url: str) -> tuple[str, ...]:
    response = requests.get(f"{url}.idx", timeout=(10, 30))
    response.raise_for_status()
    return tuple(line for line in response.text.splitlines() if line.strip())


def _inspect_message(job: MessageJob) -> GribMessage:
    lines = _inventory_lines(job.url)
    if job.source != "gfs" or job.accumulation_start_hour is None:
        matches = [(index, line) for index, line in enumerate(lines) if job.selector in line]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one inventory match for {job.selector!r}; found {len(matches)}")
        index, line = matches[0]
    else:
        exact = f":APCP:surface:{job.accumulation_start_hour}-{job.forecast_hour} hour acc fcst:"
        matches = [(index, line) for index, line in enumerate(lines) if exact in line]
        if len(matches) == 2 and job.accumulation_start_hour == 0 and job.forecast_hour == 6:
        # NCEP lists both six-hour and cumulative-to-f006 APCP. Their windows
        # coincide only at f006; the first inventory entry is the interval field.
            index, line = matches[0]
        elif len(matches) == 1:
            index, line = matches[0]
        else:
            raise ValueError(f"Expected one exact GFS APCP interval {exact}, found {len(matches)}")
    fields = line.split(":")
    start = int(fields[1])
    end = int(lines[index + 1].split(":")[1]) - 1 if index + 1 < len(lines) else None
    return GribMessage(start, end, ":".join(fields[3:]))


def download_message(job: MessageJob, max_message_mib: float = 16.0, budget=None) -> Path:
    """Fetch one GRIB inventory-selected message with byte-range/partial-file safety.

    The caller must explicitly invoke this after reviewing the estimator. A cached
    V1 message is returned untouched. New V2 messages use a .part file and atomic
    replacement only after length and GRIB sentinels pass.
    """
    provenance_path = job.target.with_suffix(job.target.suffix + ".provenance.json")
    pending_provenance = provenance_path.with_suffix(provenance_path.suffix + ".pending")
    if job.target.is_file() and job.target.stat().st_size > 0:
        if job.reuse_legacy_cache:
            return job.target
        if not provenance_path.is_file() and pending_provenance.is_file():
            pending = json.loads(pending_provenance.read_text(encoding="utf-8"))
            if pending.get("url") == job.url and pending.get("sha256") == sha256(job.target.read_bytes()).hexdigest():
                os.replace(pending_provenance, provenance_path)
        if not provenance_path.is_file():
            raise ValueError(f"V2 GRIB cache lacks completion provenance: {job.target}")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        if (provenance.get("url") != job.url or provenance.get("inventory_selector") != job.selector or
                provenance.get("forecast_hour") != job.forecast_hour or
                provenance.get("accumulation_start_hour") != job.accumulation_start_hour or
                provenance.get("sha256") != sha256(job.target.read_bytes()).hexdigest()):
            raise ValueError(f"V2 GRIB cache provenance/hash mismatch: {job.target}")
        _verify_accumulation(job, provenance.get("inventory_description", ""))
        _verify_instantaneous(job, provenance.get("inventory_description", ""))
        return job.target
    for attempt in range(1, MAX_TRANSFER_ATTEMPTS + 1):
        try:
            message = _inspect_message(job)
            break
        except Exception as error:
            if not _transient(error) or attempt == MAX_TRANSFER_ATTEMPTS:
                raise
            _retry_delay(attempt)
    _verify_accumulation(job, message.description)
    _verify_instantaneous(job, message.description)
    if message.size is None:
        raise ValueError("A finite GRIB byte range is required; refusing an unbounded download")
    if not 0 < message.size <= max_message_mib * 1048576:
        raise ValueError("GRIB message exceeds the configured per-message download guard")
    part = job.target.with_suffix(job.target.suffix + ".part")
    part_metadata = part.with_suffix(part.suffix + ".json")
    offset = part.stat().st_size if part.exists() else 0
    if offset > message.size:
        raise ValueError(f"Partial cache exceeds inventory size: {part}")
    if budget is not None:
        budget.ensure_capacity(message.size - offset)
    job.target.parent.mkdir(parents=True, exist_ok=True)
    expected_partial = {"url": job.url, "start": message.start, "end": message.end,
                        "size": message.size, "description": message.description}
    if part.exists():
        if not part_metadata.is_file() or json.loads(part_metadata.read_text(encoding="utf-8")) != expected_partial:
            raise ValueError(f"Partial GRIB cache has missing/mismatched inventory provenance: {part}")
    else:
        part_metadata.write_text(json.dumps(expected_partial), encoding="utf-8")
    for attempt in range(1, MAX_TRANSFER_ATTEMPTS + 1):
        offset = part.stat().st_size if part.exists() else 0
        if offset == message.size:
            break
        start = message.start + offset
        headers = {"Range": f"bytes={start}-{message.end}"}
        if budget is not None:
            budget.reserve_transfer(message.size - offset)
        try:
            with requests.get(job.url, headers=headers, timeout=(10, 30), stream=True) as response:
                response.raise_for_status()
                expected_prefix = f"bytes {start}-{message.end}/"
                if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(expected_prefix):
                    raise RuntimeError("Source did not honor the exact GRIB byte range; refusing a full file")
                with part.open("ab") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            if handle.tell() + len(chunk) > message.size:
                                raise RuntimeError("GRIB response exceeded its inventory byte range")
                            if budget is not None:
                                budget.consume(len(chunk))
                            handle.write(chunk)
            if part.stat().st_size == message.size:
                break
            raise requests.exceptions.ConnectionError("NOAA closed a GRIB range before its declared end")
        except Exception as error:
            if not _transient(error) or attempt == MAX_TRANSFER_ATTEMPTS:
                raise
            _retry_delay(attempt)
    if part.stat().st_size != message.size:
        raise RuntimeError("Incomplete GRIB message remains in .part cache for a later resume")
    with part.open("rb") as handle:
        if handle.read(4) != b"GRIB":
            raise ValueError("Selected byte range does not begin with a GRIB message")
        handle.seek(-4, 2)
        if handle.read(4) != b"7777":
            raise ValueError("Selected byte range does not end with the GRIB terminator")
    digest = sha256(part.read_bytes()).hexdigest()
    provenance = {
        "source": job.source, "url": job.url, "inventory_selector": job.selector,
        "inventory_description": message.description, "byte_start": message.start,
        "byte_end": message.end, "byte_size": message.size, "sha256": digest,
        "forecast_hour": job.forecast_hour,
        "accumulation_start_hour": job.accumulation_start_hour,
    }
    pending_provenance.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    os.replace(part, job.target)
    part_metadata.unlink()
    os.replace(pending_provenance, provenance_path)
    return job.target


def write_missing_era5_month_plans(config: dict) -> list[dict]:
    """Write request JSON only; submit with the existing CDS client after approval.

    A missing-days request gets a unique filename, so an incomplete monthly cache
    is never overwritten. The subsequent dataset validator still checks every hour.
    """
    plans = []
    raw = Path(config["paths"]["raw_dir"]) / "era5"
    for month, item in era5_month_plan(config).items():
        if not item["missing_hours"]:
            continue
        missing_dates = item["missing_dates"]
        identifier = sha256("|".join(missing_dates).encode()).hexdigest()[:12]
        target = raw / f"era5_tp_{month}_{identifier}.nc"
        request_path = raw / "requests" / f"era5_tp_{month}_{identifier}.json"
        write_era5_request_for_dates(config, missing_dates, request_path)
        plans.append({"month": month, "missing_hours": item["missing_hours"],
                      "request_path": request_path, "target": target})
    return plans


def retrieve_one_era5_month_plan(plan: dict, config: dict, credential_path: str | Path) -> Path | None:
    """Explicit one-month CDS operation, for a later approved acquisition phase.

    Uses the existing secure credential reader; validates the resulting cache
    against every required timestamp rather than accepting file existence.
    """
    from .planning import era5_month_plan

    month = plan["month"]
    current = era5_month_plan(config)[month]
    if not current["missing_hours"]:
        return None  # Coverage was completed by an existing cache; no request made.
    download_era5(plan["request_path"], credential_path, plan["target"])
    remaining = era5_month_plan(config)[month]["missing_hours"]
    if remaining:
        raise ValueError(f"ERA5 month {month} still lacks {remaining} required hourly timestamps")
    return Path(plan["target"])

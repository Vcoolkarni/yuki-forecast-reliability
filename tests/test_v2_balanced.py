from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from forecast_bust.v2.acquisition import _verify_accumulation
from forecast_bust.v2.balanced import (assemble_daily_intervals, balanced_gefs_jobs,
                                       component_hours, era5_reference_for_leads)
from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.planning import MessageJob
from forecast_bust.v2.budget_planning import load_budget_config
from forecast_bust.v2.recommended_acquisition import jobs_for_date
from forecast_bust.v2.recommended_dataset import recommended_forecast_config


@pytest.mark.parametrize("lead,hours", [
    (1, [6, 12, 18, 24]),
    (5, [102, 108, 114, 120]),
    (10, [222, 228, 234, 240]),
])
def test_exact_gfs_day_assembly_and_missing_interval_failure(lead, hours, tmp_path):
    assert component_hours(lead) == hours
    items = []
    for hour in hours:
        job = MessageJob("gfs", "2022-07-01", hour, "precipitation", "https://example.org/gfs",
                         ":APCP:surface:", tmp_path / f"f{hour}.grb2", accumulation_start_hour=hour - 6)
        _verify_accumulation(job, f"APCP:surface:{hour-6}-{hour} hour acc fcst:")
        frame = pd.DataFrame({"latitude": [20.0, 20.0], "longitude": [76.0, 76.25],
                              "value": [float(hour / 6), 1.0]})
        items.append((job, frame))
    daily = assemble_daily_intervals(items, lead, "gfs_daily")
    assert daily.forecast_precipitation.tolist() == [sum(hour / 6 for hour in hours), 4.0]
    with pytest.raises(ValueError, match="Incomplete"):
        assemble_daily_intervals(items[:-1], lead, "gfs_daily")
    with pytest.raises(ValueError, match="does not match"):
        _verify_accumulation(items[0][0], f"APCP:surface:0-{hours[0]} hour acc fcst:") if lead > 1 else _verify_accumulation(items[0][0], f"APCP:surface:0-{hours[0]+6} hour acc fcst:")
    overlapping = list(items)
    bad_job = deepcopy(overlapping[1][0])
    bad_job = MessageJob(bad_job.source, bad_job.initialization_date, bad_job.forecast_hour,
                         bad_job.variable, bad_job.url, bad_job.selector, bad_job.target,
                         accumulation_start_hour=bad_job.accumulation_start_hour - 6)
    overlapping[1] = (bad_job, overlapping[1][1])
    with pytest.raises(ValueError, match="Overlapping"):
        assemble_daily_intervals(overlapping, lead, "gfs_daily")


def test_balanced_gefs_products_are_mean_and_interval_spread_not_daily_spread(tmp_path):
    config = load_v2_config()
    config["paths"]["raw_dir"] = str(tmp_path)
    jobs = balanced_gefs_jobs(config, "2022-07-01", [1, 10])
    assert len(jobs) == 16
    assert sorted({job.forecast_hour for job in jobs}) == [6, 12, 18, 24, 222, 228, 234, 240]
    for job in jobs:
        marker = "ens mean" if job.variable == "precipitation_mean_6h" else "ens std dev"
        _verify_accumulation(job, f"APCP:surface:{job.forecast_hour-6}-{job.forecast_hour} hour acc fcst:{marker}")
    spread = [(job, pd.DataFrame({"latitude": [20.0], "longitude": [76.0], "value": [float(i)]}))
              for i, job in enumerate(jobs[:8], start=1) if job.variable == "precipitation_spread_6h"]
    mean = assemble_daily_intervals(spread, 1, "gefs_6h_spread_mean")
    maximum = assemble_daily_intervals(spread, 1, "gefs_6h_spread_max")
    assert mean.gefs_6h_spread_mean_mm.iloc[0] == 5.0
    assert maximum.gefs_6h_spread_max_mm.iloc[0] == 8.0
    assert "gefs_precipitation_std_mm" not in mean.columns
    with pytest.raises(ValueError, match="Expected published GEFS ensemble spread"):
        _verify_accumulation(spread[0][0], "APCP:surface:0-6 hour acc fcst:ens mean")


def test_gfs_idx_chooses_exact_six_hour_field_not_cumulative(monkeypatch, tmp_path):
    import forecast_bust.v2.acquisition as acquisition

    lines = "\n".join([
        "1:0:d=2022070100:APCP:surface:6-12 hour acc fcst:",
        "2:100:d=2022070100:APCP:surface:0-12 hour acc fcst:",
        "3:200:d=2022070100:TMP:2 m above ground:12 hour fcst:",
    ])

    class Response:
        text = lines
        def raise_for_status(self): pass

    monkeypatch.setattr(acquisition.requests, "get", lambda *_args, **_kwargs: Response())
    job = MessageJob("gfs", "2022-07-01", 12, "precipitation", "https://example.org/grib",
                     ":APCP:surface:", tmp_path / "f012.grb2", accumulation_start_hour=6)
    message = acquisition._inspect_message(job)
    assert (message.start, message.end) == (0, 99)
    assert "6-12 hour" in message.description

    first_six = "\n".join([
        "1:0:d=2022070100:APCP:surface:0-6 hour acc fcst:",
        "2:100:d=2022070100:APCP:surface:0-6 hour acc fcst:",
        "3:200:d=2022070100:TMP:2 m above ground:6 hour fcst:",
    ])
    Response.text = first_six
    acquisition._inventory_lines.cache_clear()  # Test changes the same URL's immutable real-world inventory.
    first = MessageJob("gfs", "2022-07-01", 6, "precipitation", "https://example.org/grib",
                       ":APCP:surface:", tmp_path / "f006.grb2", accumulation_start_hour=0)
    assert acquisition._inspect_message(first).start == 0


def test_era5_exact_24_hour_endpoints_and_missing_hour_rejection():
    # An in-memory unit-test fixture; operational code never substitutes data.
    hours = pd.date_range("2022-07-01T01:00:00", "2022-07-11T00:00:00", freq="h")
    dataset = xr.Dataset({"tp": (("time", "latitude", "longitude"), np.full((len(hours), 2, 2), .001), {"units": "m"})},
                         coords={"time": hours, "latitude": [20.25, 20.0], "longitude": [76.0, 76.25]})
    geography = {"south": 20.0, "north": 20.25, "west": 76.0, "east": 76.25,
                 "grid_resolution_degrees": .25}
    reference = era5_reference_for_leads(dataset, "2022-07-01", [1, 10], geography)
    assert len(reference) == 8
    assert np.allclose(reference.reference_precipitation, 24.0)
    assert set(reference.valid_time.dt.strftime("%Y-%m-%d")) == {"2022-07-02", "2022-07-11"}
    missing = dataset.drop_sel(time=np.datetime64("2022-07-11T00:00:00"))
    with pytest.raises(ValueError, match="Missing ERA5 hourly endpoints"):
        era5_reference_for_leads(missing, "2022-07-01", [1, 10], geography)


def test_era5_native_quarter_degree_selects_exact_half_degree_centers():
    hours = pd.date_range("2022-07-01T01:00:00", periods=24, freq="h")
    native = xr.Dataset({"tp": (("time", "latitude", "longitude"),
                                np.full((24, 3, 3), .001), {"units": "m"})},
                        coords={"time": hours, "latitude": [20.5, 20.25, 20.0],
                                "longitude": [76.0, 76.25, 76.5]})
    half = {"south": 20.0, "north": 20.5, "west": 76.0, "east": 76.5,
            "grid_resolution_degrees": .5}
    reference = era5_reference_for_leads(native, "2022-07-01", [1], half)
    assert len(reference) == 4
    assert set(zip(reference.latitude, reference.longitude)) == {
        (20.0, 76.0), (20.0, 76.5), (20.5, 76.0), (20.5, 76.5)}
    assert np.allclose(reference.reference_precipitation, 24.0)


def test_recommended_gefs_spread_is_end_interval_not_daily(monkeypatch, tmp_path):
    import forecast_bust.v2.balanced as balanced

    base, budget = load_v2_config(), load_budget_config()
    config = recommended_forecast_config(base, budget)
    config["geography"].update({"south": 20.0, "north": 20.5, "west": 76.0, "east": 76.5})
    jobs = [job for job in jobs_for_date(base, budget, "2021-06-01", tmp_path)
            if job.forecast_hour <= 24]
    def decoded(job, _geography):
        value = 1.0 if job.variable == "precipitation" else 2.0
        if job.variable == "precipitation_spread_6h":
            value = 3.0
        return pd.DataFrame({"latitude": [20.0, 20.0, 20.5, 20.5],
                             "longitude": [76.0, 76.5, 76.0, 76.5],
                             "value": [value] * 4})
    monkeypatch.setattr(balanced, "decode_message", decoded)
    forecast, provenance = balanced.assemble_balanced_forecast(
        config, "2021-06-01", [1], [job for job in jobs if job.source == "gfs"],
        [job for job in jobs if job.source == "gefs"])
    assert len(forecast) == 4
    assert (forecast.gefs_end_window_spread_6h_mm == 3).all()
    assert "gefs_precipitation_std_mm" not in forecast
    assert provenance["1"]["gefs_spread_component_forecast_hours"] == [24]

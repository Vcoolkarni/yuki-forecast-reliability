from copy import deepcopy

import pytest

from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.profile_planning import estimate_profiles, load_profile_config


def _plans(tmp_path):
    base = deepcopy(load_v2_config())
    base["paths"]["legacy_gfs_dir"] = str(tmp_path / "no_legacy_cache")
    return estimate_profiles(base, load_profile_config())


def test_all_profiles_and_cadences_are_offline_and_separate_unsupported_2020(tmp_path):
    plans = _plans(tmp_path)
    assert len(plans) == 9
    for plan in plans:
        assert plan["DATE_RANGE"][0].startswith("2021-")
        assert plan["DATE_RANGE"][-1] == "2025-09-30" or plan["SAMPLING_FREQUENCY"] != "every 1 day"
        assert "2020" in plan["UNSUPPORTED_PERIODS"]
        assert "gfs_0p25" in plan["UNSUPPORTED_PERIODS"]["2020"]["sources"]
        assert plan["INITIALIZATIONS_BY_PERIOD"]["test"] > 0
        assert sum(plan["INITIALIZATIONS_BY_PERIOD"].values()) == plan["INITIALIZATIONS"]
        assert plan["TOTAL_REQUESTS"] == 2 * (plan["GFS_MESSAGES"] + plan["GEFS_MESSAGES"]) + plan["ERA5_MONTHS"]
        assert plan["ESTIMATED_INTERMEDIATE_DISK_GIB"] > plan["ESTIMATED_DOWNLOAD_GIB"]
        assert plan["GRID_ROWS_AFTER_MASK_ESTIMATE"] < plan["GRID_ROWS"]
        assert plan["THREE_DAY_BLOCKS"] <= plan["INITIALIZATIONS"]


def test_precipitation_intervals_and_profile_costs(tmp_path):
    plans = {(p["PROFILE_NAME"], p["SAMPLING_FREQUENCY"]): p for p in _plans(tmp_path)}
    light = plans["LIGHT", "every 1 day"]
    balanced = plans["BALANCED", "every 1 day"]
    full = plans["FULL", "every 1 day"]
    assert light["INITIALIZATIONS"] == 5 * 122
    assert light["UNSUPPORTED_PERIODS"]["2020"]["initializations"] == 122
    assert light["GFS_MESSAGES"] == 610 * (13 * 10 + 4 * 10)
    assert light["GEFS_MESSAGES"] == 0
    assert balanced["GEFS_MESSAGES"] == 610 * 2 * 40
    assert full["GEFS_MESSAGES"] == 610 * 31 * 40
    assert light["ERA5_MONTHS"] == balanced["ERA5_MONTHS"] == full["ERA5_MONTHS"] == 25
    assert light["ESTIMATED_DOWNLOAD_GIB"] < balanced["ESTIMATED_DOWNLOAD_GIB"] < full["ESTIMATED_DOWNLOAD_GIB"]
    assert plans["BALANCED", "every 2 days"]["INITIALIZATIONS"] == 305
    assert plans["BALANCED", "every 3 days"]["INITIALIZATIONS"] == 205
    assert all(plans["BALANCED", cadence]["THREE_DAY_BLOCKS"] == 205
               for cadence in ("every 1 day", "every 2 days", "every 3 days"))


def test_invalid_profile_modes_fail(tmp_path):
    base = load_v2_config()
    base["paths"]["legacy_gfs_dir"] = str(tmp_path / "none")
    profiles = deepcopy(load_profile_config())
    profiles["profiles"]["BALANCED"]["gefs_mode"] = "fake_member_spread"
    with pytest.raises(ValueError, match="Unsupported GEFS mode"):
        estimate_profiles(base, profiles)

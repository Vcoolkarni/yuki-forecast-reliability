from copy import deepcopy

import pytest

from forecast_bust.v2.budget_planning import estimate_budget_profiles, load_budget_config
from forecast_bust.v2.configuration import load_v2_config


def _plans(tmp_path):
    base = deepcopy(load_v2_config())
    base["paths"]["raw_dir"] = str(tmp_path / "empty")
    return estimate_budget_profiles(base, load_budget_config())


def test_budget_profiles_preserve_five_years_and_untouched_2025_split(tmp_path):
    plans = {item["PROFILE_NAME"]: item for item in _plans(tmp_path)}
    assert set(plans) == {"ULTRALIGHT", "RECOMMENDED", "MAX"}
    assert [plans[name]["INITIALIZATIONS"] for name in plans] == [105, 175, 205]
    assert [plans[name]["INITIALIZATIONS_BY_PERIOD"] for name in plans] == [
        {"train": 63, "validation": 21, "test": 21},
        {"train": 105, "validation": 35, "test": 35},
        {"train": 123, "validation": 41, "test": 41},
    ]
    for item in plans.values():
        assert item["YEARS"] == "2021–2025"
        assert item["TEST_PERIOD"]["start_date"] == "2025-06-01"
        assert item["GRID_CELLS_PER_LEAD"] == 63 * 61
        assert item["CACHE"]["REUSABLE_MATCHING_FILES"] == 0


def test_messages_and_hard_cap(tmp_path):
    plans = {item["PROFILE_NAME"]: item for item in _plans(tmp_path)}
    for name, gefs_per_init in (("ULTRALIGHT", 20), ("RECOMMENDED", 50), ("MAX", 80)):
        item = plans[name]
        assert item["GFS_MESSAGES"] == item["INITIALIZATIONS"] * 110
        assert item["GEFS_MESSAGES"] == item["INITIALIZATIONS"] * gefs_per_init
        assert item["ERA5_MONTHS"] == 25
        assert item["TOTAL_ESTIMATED_DOWNLOAD_GIB"] <= item["TARGET_DOWNLOAD_GIB"]
    assert plans["ULTRALIGHT"]["WITHIN_HARD_8_GIB_CAP"]
    assert plans["RECOMMENDED"]["WITHIN_HARD_8_GIB_CAP"]
    assert not plans["MAX"]["WITHIN_HARD_8_GIB_CAP"]
    assert plans["RECOMMENDED"]["INITIALIZATION_DATES_PER_GIB"] > plans["MAX"]["INITIALIZATION_DATES_PER_GIB"]


def test_invalid_assumptions_cannot_understate_cost(tmp_path):
    base = deepcopy(load_v2_config())
    base["paths"]["raw_dir"] = str(tmp_path / "empty")
    config = deepcopy(load_budget_config())
    config["era5"]["estimate_mib_per_month"] = 1.0
    with pytest.raises(ValueError, match="ERA5 monthly budget"):
        estimate_budget_profiles(base, config)
    config = deepcopy(load_budget_config())
    config["estimation"]["observed_message_padding_factor"] = 0.5
    with pytest.raises(ValueError, match="padding"):
        estimate_budget_profiles(base, config)

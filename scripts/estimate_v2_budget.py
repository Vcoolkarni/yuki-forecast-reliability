"""Compare ULTRALIGHT/RECOMMENDED/MAX V2 plans without network or writes."""

import json

from forecast_bust.v2.budget_planning import estimate_budget_profiles, load_budget_config
from forecast_bust.v2.configuration import load_v2_config


if __name__ == "__main__":
    print(json.dumps(estimate_budget_profiles(load_v2_config(), load_budget_config()), indent=2))

"""Print offline V2 LIGHT/BALANCED/FULL acquisition comparisons as JSON."""

import argparse
import json

from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.profile_planning import estimate_profiles, load_profile_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", default="config/v2.yaml")
    parser.add_argument("--profiles-config", default="config/v2_profiles.yaml")
    args = parser.parse_args()
    print(json.dumps(estimate_profiles(load_v2_config(args.base_config), load_profile_config(args.profiles_config)), indent=2))


if __name__ == "__main__":
    main()

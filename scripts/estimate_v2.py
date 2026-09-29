"""Offline-only V2 acquisition estimate. Never contacts NOAA or CDS."""

import argparse
import json

from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.planning import estimate_acquisition


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/v2.yaml")
    args = parser.parse_args()
    print(json.dumps(estimate_acquisition(load_v2_config(args.config)), indent=2))


if __name__ == "__main__":
    main()

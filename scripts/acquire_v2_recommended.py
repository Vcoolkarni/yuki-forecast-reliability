"""Opt-in RECOMMENDED 0.5° V2 acquisition with a persistent hard 8 GiB cap."""

import argparse
from pathlib import Path

from forecast_bust.v2.budget_planning import load_budget_config
from forecast_bust.v2.byte_budget import DownloadLimitReached
from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.recommended_acquisition import run_recommended


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-download", action="store_true", required=True,
                        help="Explicit acknowledgement that up to 8 GiB may be downloaded")
    parser.add_argument("--credentials", default=".secrets/cds_credentials.txt")
    args = parser.parse_args()
    try:
        run_recommended(load_v2_config(), load_budget_config(), Path(args.credentials))
    except DownloadLimitReached as error:
        print(f"STOPPED_AT_HARD_BYTE_LIMIT: {error}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()

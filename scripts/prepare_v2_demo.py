"""Extract two real 2024 forecasts into a forecast-only historical demo feed."""

from pathlib import Path
import pandas as pd

from forecast_bust.v2.dataset import IDENTITY, TARGETS


root = Path("data/processed/v2/recommended_0p50/validation")
destination = Path("data/interim/v2_historical_demo_forecasts.csv.gz")
features = ["forecast_precipitation", "forecast_temperature_2m", "forecast_relative_humidity_2m",
            "forecast_mean_sea_level_pressure", "forecast_u_wind_10m", "forecast_v_wind_10m",
            "forecast_precipitable_water", "forecast_cape_surface", "forecast_wind_speed_10m",
            "precipitation_gradient_mm_per_degree", "gefs_precipitation_mean_mm",
            "gefs_end_window_spread_6h_mm", "gfs_minus_gefs_mean_precipitation_mm"]
columns = IDENTITY + features
frames = [pd.read_csv(root / f"{day}.raw.csv.gz", usecols=columns)
          for day in ("2024-09-26", "2024-09-29")]
output = pd.concat(frames, ignore_index=True)
if set(output.columns) & TARGETS or len(output) != 2 * 38430:
    raise ValueError("Historical demo source is incomplete or contains target data")
destination.parent.mkdir(parents=True, exist_ok=True)
output.to_csv(destination, index=False, compression="gzip")
print(f"HISTORICAL_DEMO={destination} ROWS={len(output)} TARGET_COLUMNS=0")

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import yaml

from forecast_bust.acquisition import inspect_gfs_grib_message
from forecast_bust.date_selection import configured_initialization_dates


cfg = yaml.safe_load(Path("config/phase2.yaml").read_text())
predictors = cfg["forecast"]["predictors"]
raw = Path(cfg["paths"]["raw_dir"]) / "gfs_phase2"
jobs = [(date.replace("-", ""), lead, name) for date in configured_initialization_dates(cfg) for lead in cfg["forecast"]["lead_days"] for name in cfg["forecast"]["variables"]]


def inspect(job):
    date, lead, name = job
    hour = lead * 24
    predictor = predictors[name]
    cached = raw / f"gfs_{date}_00_f{hour:03d}_{predictor['cache_suffix']}.grb2"
    if cached.is_file() and cached.stat().st_size > 0:
        return 0
    url = f"https://noaa-gfs-bdp-pds.s3.amazonaws.com/gfs.{date}/00/atmos/gfs.t00z.pgrb2.0p25.f{hour:03d}"
    selector = predictor["selector_template"].format(lead=lead)
    message = inspect_gfs_grib_message(url, selector)
    return message.size


with ThreadPoolExecutor(max_workers=6) as pool:
    sizes = list(pool.map(inspect, jobs))

if any(size is None for size in sizes):
    raise RuntimeError("At least one selected message has no finite byte range")
print(f"REQUESTS={len(sizes)}")
print(f"CACHED={sum(size == 0 for size in sizes)}")
print(f"NEW_REQUESTS={sum(size > 0 for size in sizes)}")
print(f"ESTIMATED_BYTES={sum(sizes)}")
print(f"ESTIMATED_MIB={sum(sizes) / 1048576:.2f}")
print(f"MIN_MAX_MESSAGE_BYTES={min(sizes)},{max(sizes)}")

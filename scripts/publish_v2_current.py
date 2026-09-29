"""Discover and publish one complete current NOAA forecast without ERA5 or training."""

from pathlib import Path
import os
import yaml

from forecast_bust.v2.current import publish_current_run
from forecast_bust.v2.current_store import CurrentObjectStore

root = Path(__file__).resolve().parents[1]
base = yaml.safe_load((root / "config/v2.yaml").read_text(encoding="utf-8"))
budget = yaml.safe_load((root / "config/v2_budget_profiles.yaml").read_text(encoding="utf-8"))
settings = yaml.safe_load((root / "config/v2_current.yaml").read_text(encoding="utf-8"))
if os.environ.get("RENDER") == "true" and not os.environ.get("FORECAST_BUST_OBJECT_BUCKET"):
    raise RuntimeError("Production forecast publisher requires persistent object storage")
try:
    object_store = CurrentObjectStore.from_environment()
except Exception as error:
    raise RuntimeError(f"Object-store configuration failed ({type(error).__name__})") from None
if object_store is not None:
    # Cron filesystems are ephemeral. Mirroring the last complete run first
    # makes a retry of the same NOAA cycle idempotent without re-downloading it.
    try:
        object_store.sync_latest(root / settings["processed_dir"])
    except Exception as error:
        raise RuntimeError(f"Processed-run restore failed ({type(error).__name__})") from None
manifest = publish_current_run(base, budget, settings, root)
if object_store is not None:
    try:
        object_store.publish(root / settings["processed_dir"], manifest["run_id"])
    except Exception as error:
        raise RuntimeError(f"Processed-run publication failed ({type(error).__name__})") from None
    print(f"CURRENT_RUN_OBJECT_PUBLISHED={manifest['run_id']}")

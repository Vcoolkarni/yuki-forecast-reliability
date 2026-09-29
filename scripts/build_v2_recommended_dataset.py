"""Build V2 RECOMMENDED historical partitions from completed local caches only."""

from pathlib import Path

from forecast_bust.v2.budget_planning import load_budget_config
from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.recommended_dataset import build_recommended_dataset


if __name__ == "__main__":
    output = Path("data/processed/v2/recommended_0p50")
    manifest = build_recommended_dataset(load_v2_config(), load_budget_config(), output_root=output)
    print(f"DATASET_MANIFEST={output / 'dataset_manifest.json'}")
    print(f"ROWS={sum(manifest['rows'].values())}")
    print(f"INITIALIZATIONS={sum(manifest['initializations'].values())}")

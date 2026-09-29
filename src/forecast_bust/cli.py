from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

from .acquisition import write_era5_request
from .config import ensure_directories, load_config
from .explain import save_shap_summary
from .features import build_features
from .labeling import add_error_and_labels
from .matching import match_forecast_reference
from .schema import validate_dataset
from .training import save_training_outputs, train


def main() -> None:
    parser = argparse.ArgumentParser(prog="forecast-bust")
    parser.add_argument("--config", default="config/default.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("plan-era5")
    match = sub.add_parser("match")
    match.add_argument("--forecast", required=True)
    match.add_argument("--reference", required=True)
    match.add_argument("--output", default="data/processed/dataset.csv")
    fit = sub.add_parser("train")
    fit.add_argument("--dataset", default="data/processed/dataset.csv")
    args = parser.parse_args()
    cfg = load_config(args.config)
    ensure_directories(cfg)
    if args.command == "init":
        print("Project directories initialized. No data were downloaded.")
    elif args.command == "plan-era5":
        output = write_era5_request(cfg, Path(cfg["paths"]["interim_dir"]) / "era5_request.json")
        print(f"Wrote request plan to {output}; it has NOT been submitted.")
    elif args.command == "match":
        forecast = pd.read_csv(args.forecast)
        reference = pd.read_csv(args.reference)
        matched = match_forecast_reference(forecast, reference, cfg["reference"]["match_tolerance_hours"])
        labeled = add_error_and_labels(matched, cfg["labeling"])
        validated = validate_dataset(labeled)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        validated.to_csv(args.output, index=False)
        print(f"Wrote {len(validated)} verified matched rows to {args.output}")
    elif args.command == "train":
        frame = validate_dataset(pd.read_csv(args.dataset))
        model, metrics, test_frame, probabilities = train(frame, cfg["model"])
        test_frame = test_frame.copy()
        test_frame["bust_probability"] = probabilities
        test_frame["forecast_confidence"] = 1.0 - probabilities
        save_training_outputs(model, metrics, Path(cfg["paths"]["model_dir"]) / "xgboost.joblib", Path(cfg["paths"]["report_dir"]) / "metrics.json")
        test_frame.to_csv(Path(cfg["paths"]["report_dir"]) / "predictions.csv", index=False)
        save_shap_summary(model, build_features(test_frame), Path(cfg["paths"]["report_dir"]) / "shap_summary.png")
        print(metrics)


if __name__ == "__main__":
    main()


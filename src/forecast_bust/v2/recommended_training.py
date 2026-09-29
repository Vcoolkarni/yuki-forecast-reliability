"""Train RECOMMENDED V2 without consulting 2025 until selection is frozen."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
import yaml
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier, XGBRegressor

from ..decision import select_validation_threshold
from .dataset import TARGETS
from .evaluation import classification_metrics, regression_metrics
from .feature_schema import forecast_feature_schema
from .recommended_dataset import recommended_forecast_config


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_split(root: Path, split: str, dates: list[str], features: list[str],
                rows: int, include_identity: bool = False) -> dict:
    matrix = np.empty((rows, len(features)), dtype=np.float32)
    labels = np.empty(rows, dtype=np.int8)
    errors = np.empty(rows, dtype=np.float32)
    leads = np.empty(rows, dtype=np.int8)
    groups = np.empty(rows, dtype="U10")
    identity_parts = []
    offset = 0
    columns = list(dict.fromkeys(features + ["is_bust", "target_absolute_error_mm", "lead_day"]
                                 + (["initialization_time", "valid_time", "latitude", "longitude"]
                                    if include_identity else [])))
    for day in dates:
        path = root / split / f"{day}.csv.gz"
        if not path.is_file():
            raise FileNotFoundError(f"Labeled V2 partition is missing: {path}")
        part = pd.read_csv(path, usecols=columns)
        length = len(part)
        if length != 38430 or offset + length > rows:
            raise ValueError(f"Unexpected V2 grid size in {path}: {length}")
        matrix[offset:offset + length] = part[features].to_numpy(dtype=np.float32)
        labels[offset:offset + length] = part.is_bust.to_numpy(dtype=np.int8)
        errors[offset:offset + length] = part.target_absolute_error_mm.to_numpy(dtype=np.float32)
        leads[offset:offset + length] = part.lead_day.to_numpy(dtype=np.int8)
        groups[offset:offset + length] = day
        if include_identity:
            identity_parts.append(part[["initialization_time", "valid_time", "latitude", "longitude", "lead_day"]])
        offset += length
    if offset != rows or not np.isfinite(matrix).all() or not np.isfinite(errors).all():
        raise ValueError(f"V2 {split} split has incomplete or non-finite predictor/target data")
    return {"X": matrix, "y": labels, "error": errors, "lead": leads,
            "group": groups, "identity": pd.concat(identity_parts, ignore_index=True)
            if include_identity else None}


def _calibrate(calibrator: LogisticRegression, raw: np.ndarray) -> np.ndarray:
    clipped = np.clip(raw, 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    return calibrator.predict_proba(logits)[:, 1]


def _calibration_bins(truth: np.ndarray, probability: np.ndarray) -> list[dict]:
    result = []
    for index in range(10):
        low, high = index / 10, (index + 1) / 10
        mask = (probability >= low) & (probability < high if index < 9 else probability <= high)
        result.append({"probability_range": [low, high], "count": int(mask.sum()),
                       "mean_probability": float(probability[mask].mean()) if mask.any() else None,
                       "observed_bust_rate": float(truth[mask].mean()) if mask.any() else None})
    return result


def _by_lead(data: dict, probability: np.ndarray, expected_error: np.ndarray,
             threshold: float) -> dict:
    return {str(lead): {
        "classification": classification_metrics(data["y"][mask], probability[mask], threshold),
        "regression": regression_metrics(data["error"][mask], expected_error[mask])}
        for lead in range(1, 11) for mask in [data["lead"] == lead]}


def train_recommended(base: dict, budget_config: dict,
                      data_root: Path = Path("data/processed/v2/recommended_0p50"),
                      model_root: Path = Path("models/v2/recommended_0p50"),
                      report_root: Path = Path("reports/v2/recommended_0p50")) -> dict:
    manifest_path = data_root / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["initializations"] != {"train": 105, "validation": 35, "final_test_untouched": 35}:
        raise ValueError("RECOMMENDED V2 dataset must have the approved 105/35/35 date split")
    split_years = {"train": {2021, 2022, 2023}, "validation": {2024},
                   "final_test_untouched": {2025}}
    seen_dates: set[str] = set()
    for split, years in split_years.items():
        dates = manifest["dates"][split]
        if dates != sorted(set(dates)) or {int(day[:4]) for day in dates} != years:
            raise ValueError(f"V2 {split} dates are not unique, chronological, and within their approved years")
        if seen_dates.intersection(dates):
            raise ValueError("V2 initialization dates overlap across splits")
        seen_dates.update(dates)
    if (pd.Timestamp(manifest["dates"]["validation"][0]) -
            pd.Timestamp(manifest["dates"]["train"][-1])).days < 10 or (
            pd.Timestamp(manifest["dates"]["final_test_untouched"][0]) -
            pd.Timestamp(manifest["dates"]["validation"][-1])).days < 10:
        raise ValueError("V2 split embargo is shorter than the Day-10 verification window")
    features = list(forecast_feature_schema(recommended_forecast_config(base, budget_config)))
    if set(features) & TARGETS or "day_of_year" in features or "month" in features:
        raise ValueError("Reference, target, or event-memorization feature reached V2 training")
    if (model_root / "frozen_selection.json").exists() or (report_root / "final_test_metrics.json").exists():
        raise ValueError("V2 selection/test artifacts already exist; refusing a second final-test evaluation")
    train = _load_split(data_root, "train", manifest["dates"]["train"], features, manifest["rows"]["train"])
    validation = _load_split(data_root, "validation", manifest["dates"]["validation"],
                             features, manifest["rows"]["validation"])
    positives = int(train["y"].sum())
    if positives == 0 or positives == len(train["y"]):
        raise ValueError("Training split must contain both bust classes")
    weight = (len(train["y"]) - positives) / positives
    seed = int(base["project"]["random_seed"])
    classifier = XGBClassifier(n_estimators=300, max_depth=5, learning_rate=.06,
                               subsample=.8, colsample_bytree=.8, tree_method="hist",
                               objective="binary:logistic", eval_metric="logloss",
                               scale_pos_weight=weight, random_state=seed, n_jobs=6)
    classifier.fit(train["X"], train["y"], verbose=False)
    regressor = XGBRegressor(n_estimators=250, max_depth=5, learning_rate=.06,
                            subsample=.8, colsample_bytree=.8, tree_method="hist",
                            objective="reg:squarederror", eval_metric="rmse",
                            random_state=seed, n_jobs=6)
    regressor.fit(train["X"], train["error"], verbose=False)

    raw_validation = classifier.predict_proba(validation["X"])[:, 1]
    validation_dates = manifest["dates"]["validation"]
    calibration_dates = set(validation_dates[:18])
    threshold_dates = set(validation_dates[18:])
    calibration_mask = np.isin(validation["group"], list(calibration_dates))
    threshold_mask = np.isin(validation["group"], list(threshold_dates))
    if set(np.unique(validation["y"][calibration_mask])) != {0, 1} or set(np.unique(validation["y"][threshold_mask])) != {0, 1}:
        raise ValueError("Both 2024 calibration and threshold groups need two classes")
    calibrator = LogisticRegression(random_state=seed)
    clipped = np.clip(raw_validation[calibration_mask], 1e-6, 1 - 1e-6)
    calibrator.fit(np.log(clipped / (1 - clipped)).reshape(-1, 1), validation["y"][calibration_mask])
    calibrated_validation = _calibrate(calibrator, raw_validation)
    selection = select_validation_threshold(validation["y"][threshold_mask],
                                            calibrated_validation[threshold_mask])
    threshold = selection["threshold"]
    validation_error = np.maximum(0, regressor.predict(validation["X"]))
    validation_report = {"classification": classification_metrics(validation["y"], calibrated_validation, threshold),
                         "regression": regression_metrics(validation["error"], validation_error),
                         "calibration": _calibration_bins(validation["y"], calibrated_validation),
                         "per_lead": _by_lead(validation, calibrated_validation, validation_error, threshold),
                         "calibration_dates": sorted(calibration_dates),
                         "threshold_selection_dates": sorted(threshold_dates),
                         "note": "Selection diagnostics only; 2024 is used for calibration and threshold selection."}

    model_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    classifier_path = model_root / "bust_classifier.joblib"
    regressor_path = model_root / "expected_absolute_error.joblib"
    calibrator_path = model_root / "platt_calibrator.joblib"
    joblib.dump(classifier, classifier_path)
    joblib.dump(regressor, regressor_path)
    joblib.dump(calibrator, calibrator_path)
    feature_path = model_root / "feature_schema.json"
    feature_path.write_text(json.dumps({"features": features, "schema": forecast_feature_schema(
        recommended_forecast_config(base, budget_config))}, indent=2), encoding="utf-8")
    sample = validation["X"][::max(1, len(validation["X"]) // 2000)][:2000]
    contributions = classifier.get_booster().predict(
        xgb.DMatrix(sample, feature_names=features), pred_contribs=True)
    explain_path = report_root / "validation_model_contributions.json"
    explain_path.write_text(json.dumps({"method": "XGBoost TreeSHAP contributions on 2024 validation rows",
        "not_causal": True, "sample_rows": len(sample),
        "mean_absolute_contribution": {name: float(value) for name, value in zip(
            features, np.abs(contributions[:, :-1]).mean(axis=0))}}, indent=2), encoding="utf-8")
    frozen = {"model_version": "v2-recommended-0p50", "feature_schema": str(feature_path),
              "features": features, "dataset_manifest_sha256": _sha(manifest_path),
              "classifier_sha256": _sha(classifier_path), "regressor_sha256": _sha(regressor_path),
              "calibrator_sha256": _sha(calibrator_path),
              "training_lead_p90_thresholds_mm": manifest["thresholds_mm"],
              "scale_pos_weight": weight, "decision_threshold": threshold,
              "threshold_selection": selection,
              "train_dates": manifest["dates"]["train"],
              "calibration_dates": sorted(calibration_dates),
              "threshold_selection_dates": sorted(threshold_dates)}
    frozen_path = model_root / "frozen_selection.json"
    frozen_path.write_text(json.dumps(frozen, indent=2, allow_nan=False), encoding="utf-8")
    (report_root / "validation_metrics.json").write_text(
        json.dumps(validation_report, indent=2, allow_nan=False), encoding="utf-8")

    # First access to the 2025 partition is deliberately after all fitted
    # models, calibration, feature schema and decision rule are saved/frozen.
    test = _load_split(data_root, "final_test_untouched",
                       manifest["dates"]["final_test_untouched"], features,
                       manifest["rows"]["final_test_untouched"], include_identity=True)
    test_probability = _calibrate(calibrator, classifier.predict_proba(test["X"])[:, 1])
    test_error = np.maximum(0, regressor.predict(test["X"]))
    results = {"classification": classification_metrics(test["y"], test_probability, threshold),
               "regression": regression_metrics(test["error"], test_error),
               "calibration": _calibration_bins(test["y"], test_probability),
               "per_lead": _by_lead(test, test_probability, test_error, threshold),
               "bust_rate_by_split": manifest["bust_rate"],
               "decision_threshold": threshold,
               "confusion_matrix": classification_metrics(test["y"], test_probability, threshold)["confusion_matrix"]}
    prediction = test["identity"]
    prediction["actual_is_bust"] = test["y"]
    prediction["actual_absolute_error_mm"] = test["error"]
    prediction["bust_probability"] = test_probability
    prediction["is_bust_predicted"] = (test_probability >= threshold).astype(np.int8)
    prediction["expected_absolute_error_mm"] = test_error
    prediction_path = report_root / "final_test_predictions.csv.gz"
    prediction.to_csv(prediction_path, index=False, compression="gzip")
    metrics_path = report_root / "final_test_metrics.json"
    metrics_path.write_text(json.dumps(results, indent=2, allow_nan=False), encoding="utf-8")
    model_manifest = {"model_version": "v2-recommended-0p50", "status": "evaluated_not_production",
                      "default_model": "v1", "frozen_selection_sha256": _sha(frozen_path),
                      "final_test_metrics_sha256": _sha(metrics_path),
                      "final_test_predictions_sha256": _sha(prediction_path),
                      "dataset_manifest_sha256": _sha(manifest_path)}
    (model_root / "model_manifest.json").write_text(json.dumps(model_manifest, indent=2), encoding="utf-8")
    registry_path = Path("config/model_registry.yaml")
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if registry.get("default") != "v1":
        raise ValueError("V2 registration must not replace the V1 production default")
    registry["models"]["v2"].update({
        "status": "ready", "artifact": str(classifier_path).replace("\\", "/"),
        "training_period": ["2021-06-01", "2023-09-30"],
        "description": "RECOMMENDED 0.5-degree historical model; separately evaluated, not default production model."})
    registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")
    return results

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
import yaml

from .hotspots import find_hotspots
from .validation import IDENTITY_COLUMNS, WEATHER_COLUMNS, prepare_forecast, validate_feature_contract

DEFAULT_CONFIG = {
    "confidence": {"high_min": 80.0, "moderate_min": 50.0},
    "hotspots": {"probability_threshold": None, "min_cells": 2, "connectivity": 4},
    "explanations": {"top_features": 3},
}


def load_inference_config(path: str | Path | None = None) -> dict:
    config = deepcopy(DEFAULT_CONFIG)
    if path is not None:
        supplied = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for section, settings in supplied.items():
            if section not in config or not isinstance(settings, dict) or set(settings) - set(config[section]):
                raise ValueError(f"Unknown inference configuration section or setting: {section}")
            config[section].update(settings)
    return config


def confidence_from_probability(probability) -> np.ndarray:
    values = np.asarray(probability, dtype=float)
    if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
        raise ValueError("Bust probabilities must be finite and within [0, 1]")
    return 100.0 * (1.0 - values)


class ForecastInference:
    """Reusable inference service for a trusted existing Phase 2 model bundle.

    Calibration and thresholds are never fitted here. TreeSHAP values explain
    the uncalibrated XGBoost log-odds, not meteorological causality or percentage
    point changes in calibrated probabilities.
    """

    def __init__(self, bundle: dict, config: dict | None = None, model_id: str | None = None):
        required = {"model", "calibrator", "features", "decision_threshold"}
        if not required.issubset(bundle):
            raise ValueError(f"Incomplete saved model bundle: missing {sorted(required - set(bundle))}")
        validate_feature_contract(bundle["features"])
        self.bundle = bundle
        self.config = deepcopy(config if config is not None else DEFAULT_CONFIG)
        self.model_id = model_id
        self.threshold = float(bundle["decision_threshold"])
        if not np.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("Saved decision threshold must be finite and within [0, 1]")
        for estimator in (bundle["model"], bundle["calibrator"]):
            if list(estimator.classes_) != [0, 1]:
                raise ValueError("Inference requires binary estimators with class order [0, 1]")
        confidence = self.config["confidence"]
        if not 0 <= confidence["moderate_min"] < confidence["high_min"] <= 100:
            raise ValueError("Confidence boundaries must satisfy 0 <= moderate_min < high_min <= 100")
        hotspots = self.config["hotspots"]
        value = hotspots["probability_threshold"]
        if value is not None and (not np.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("Hotspot probability threshold must be within [0, 1]")
        if isinstance(hotspots["min_cells"], bool) or not isinstance(hotspots["min_cells"], int) or hotspots["min_cells"] < 1:
            raise ValueError("Hotspot minimum cell count must be a positive integer")
        if hotspots["connectivity"] not in (4, 8):
            raise ValueError("Hotspot connectivity must be 4 or 8")
        top = self.config["explanations"]["top_features"]
        if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= len(bundle["features"]):
            raise ValueError("Explanation top_features must be a valid positive feature count")

    @classmethod
    def from_artifact(cls, path: str | Path, config_path: str | Path | None = None):
        path = Path(path)
        # joblib must only load a trusted project model file.
        identifier = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(joblib.load(path), load_inference_config(config_path), identifier)

    def predict_initialization(self, forecast: pd.DataFrame) -> dict:
        frame = prepare_forecast(forecast, self.bundle["features"])
        inputs = frame[self.bundle["features"]]
        raw = np.asarray(self.bundle["model"].predict_proba(inputs))[:, 1]
        confidence_from_probability(raw)  # Explicit range/finite check before clipping logits.
        clipped = np.clip(raw, 1e-6, 1 - 1e-6)  # Matches Phase 2 calibration exactly.
        logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
        probability = np.asarray(self.bundle["calibrator"].predict_proba(logits))[:, 1]
        confidence = confidence_from_probability(probability)
        if len(probability) != len(frame):
            raise ValueError("Model returned the wrong number of predictions")
        contributions = self.bundle["model"].get_booster().predict(xgb.DMatrix(inputs), pred_contribs=True)
        if contributions.shape != (len(frame), len(inputs.columns) + 1) or not np.isfinite(contributions).all():
            raise ValueError("Invalid XGBoost TreeSHAP contribution output")
        predictions = frame[IDENTITY_COLUMNS + WEATHER_COLUMNS].copy()
        predictions["bust_probability"] = probability
        predictions["confidence_score"] = confidence
        boundaries = self.config["confidence"]
        predictions["confidence_category"] = np.where(confidence >= boundaries["high_min"], "High",
            np.where(confidence >= boundaries["moderate_min"], "Moderate", "Low"))
        predictions["is_bust_predicted"] = probability >= self.threshold
        predictions["decision_threshold"] = self.threshold
        risk_threshold = self.config["hotspots"]["probability_threshold"]
        if risk_threshold is None:
            risk_threshold = self.threshold
        hotspots = find_hotspots(predictions, risk_threshold, self.config["hotspots"]["min_cells"],
                                 self.config["hotspots"]["connectivity"])
        records = []
        for index, row in predictions.iterrows():
            record = row.to_dict()
            for key in ("initialization_time", "valid_time"):
                record[key] = row[key].isoformat().replace("+00:00", "Z")
            record["lead_day"] = int(row.lead_day)
            record["is_bust_predicted"] = bool(row.is_bust_predicted)
            top_indices = np.argsort(-np.abs(contributions[index, :-1]), kind="stable")[:self.config["explanations"]["top_features"]]
            explanations = []
            for feature_index in top_indices:
                feature = inputs.columns[feature_index]
                value = float(contributions[index, feature_index])
                direction = "increases_model_bust_score" if value > 0 else "decreases_model_bust_score" if value < 0 else "neutral"
                explanations.append({"feature": feature, "feature_value": float(inputs.iloc[index, feature_index]),
                                     "contribution": value, "direction": direction})
            record["explanations"] = explanations
            record["explanation_summary"] = "Factors influencing the model prediction: " + "; ".join(
                f"{item['feature']} ({item['feature_value']:.4g}) {item['direction'].replace('_', ' ')}"
                for item in explanations) + ". These are model attributions, not meteorological causes."
            record["explanation_base_value"] = float(contributions[index, -1])
            records.append(record)
        daily = []
        for lead, group in predictions.groupby("lead_day", sort=True):
            daily.append({"lead_day": int(lead), **self._summary(group),
                          "hotspot_count": sum(item["lead_day"] == lead for item in hotspots)})
        output = {
            "schema_version": "1.0", "model_id": self.model_id,
            "initialization_time": records[0]["initialization_time"],
            "decision_threshold": self.threshold,
            "metadata": {
                "confidence_definition": "100 * (1 - bust_probability); model-derived score, not a calibrated meteorological probability of correctness",
                "confidence_categories": boundaries,
                "hotspots": {**self.config["hotspots"], "probability_threshold": risk_threshold},
                "explanation_method": "XGBoost TreeSHAP pred_contribs",
                "contribution_units": "raw XGBoost log-odds before Platt calibration; not probability percentage points",
                "feature_units": {"forecast_precipitation": "mm per 24 hours", "forecast_temperature_2m": "K",
                    "forecast_relative_humidity_2m": "%", "forecast_mean_sea_level_pressure": "Pa",
                    "forecast_u_wind_10m": "m/s", "forecast_v_wind_10m": "m/s", "forecast_wind_speed_10m": "m/s",
                    "precipitation_gradient_mm_per_degree": "mm/degree"},
            },
            "records": records, "hotspots": hotspots, "lead_day_summaries": daily,
            "initialization_summary": {**self._summary(predictions), "lead_day_count": len(daily),
                "grid_cell_count": len(predictions[["latitude", "longitude"]].drop_duplicates()),
                "hotspot_count": len(hotspots)},
        }
        # Enforce strict JSON, including rejection of NaN/Infinity.
        json.dumps(output, allow_nan=False)
        return output

    @staticmethod
    def _summary(predictions: pd.DataFrame) -> dict:
        highest = predictions.loc[predictions.bust_probability.idxmax()]
        return {
            "number_of_predictions": int(len(predictions)),
            "mean_bust_probability": float(predictions.bust_probability.mean()),
            "maximum_bust_probability": float(predictions.bust_probability.max()),
            "mean_confidence": float(predictions.confidence_score.mean()),
            "percentage_predicted_bust": float(100 * predictions.is_bust_predicted.mean()),
            "highest_risk_location": {"latitude": float(highest.latitude), "longitude": float(highest.longitude),
                "lead_day": int(highest.lead_day), "bust_probability": float(highest.bust_probability)},
        }

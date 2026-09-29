"""Forecast-only inference using the frozen RECOMMENDED V2 artifacts."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb

from ..inference.hotspots import find_hotspots
from ..inference.service import confidence_from_probability, load_inference_config
from .dataset import IDENTITY, TARGETS, validate_forecast


class V2Inference:
    def __init__(self, model_root: Path, config_path: Path):
        frozen = json.loads((model_root / "frozen_selection.json").read_text(encoding="utf-8"))
        self.features = list(frozen["features"])
        if set(self.features) & TARGETS or "day_of_year" in self.features:
            raise ValueError("Frozen V2 model has a target or event-memorization feature")
        paths = {name: model_root / filename for name, filename in (
            ("classifier", "bust_classifier.joblib"),
            ("regressor", "expected_absolute_error.joblib"),
            ("calibrator", "platt_calibrator.joblib"))}
        for name, path in paths.items():
            if sha256(path.read_bytes()).hexdigest() != frozen[f"{name}_sha256"]:
                raise ValueError(f"Frozen V2 {name} checksum mismatch")
        schema = json.loads((model_root / "feature_schema.json").read_text(encoding="utf-8"))
        if schema["features"] != self.features:
            raise ValueError("V2 feature schema differs from frozen model")
        self.classifier = joblib.load(paths["classifier"])
        self.regressor = joblib.load(paths["regressor"])
        self.calibrator = joblib.load(paths["calibrator"])
        self.threshold = float(frozen["decision_threshold"])
        if not 0 <= self.threshold <= 1 or not np.isfinite(self.threshold):
            raise ValueError("Invalid frozen V2 decision threshold")
        self.config = load_inference_config(config_path)
        self.model_id = frozen["model_version"]

    def predict_initialization(self, forecast: pd.DataFrame) -> dict:
        if set(forecast.columns) & TARGETS:
            raise ValueError("V2 operational inference rejects ERA5/reference/target columns")
        frame = validate_forecast(forecast, self.features).reset_index(drop=True)
        if frame.initialization_time.nunique() != 1 or set(frame.lead_day) != set(range(1, 11)):
            raise ValueError("V2 inference requires one complete Day 1–10 initialization")
        inputs = frame[self.features].to_numpy(dtype=np.float32)
        raw = np.asarray(self.classifier.predict_proba(inputs))[:, 1]
        confidence_from_probability(raw)
        clipped = np.clip(raw, 1e-6, 1 - 1e-6)
        probability = self.calibrator.predict_proba(np.log(clipped / (1 - clipped)).reshape(-1, 1))[:, 1]
        confidence = confidence_from_probability(probability)
        error = np.maximum(0, self.regressor.predict(inputs))
        if not np.isfinite(error).all():
            raise ValueError("V2 regressor returned non-finite expected errors")
        contributions = self.classifier.get_booster().predict(
            xgb.DMatrix(inputs, feature_names=self.features), pred_contribs=True)
        if contributions.shape != (len(frame), len(self.features) + 1) or not np.isfinite(contributions).all():
            raise ValueError("Invalid V2 TreeSHAP contribution output")
        predictions = frame.copy()
        predictions["bust_probability"] = probability
        predictions["confidence_score"] = confidence
        bounds = self.config["confidence"]
        predictions["confidence_category"] = np.where(confidence >= bounds["high_min"], "High",
            np.where(confidence >= bounds["moderate_min"], "Moderate", "Low"))
        predictions["is_bust_predicted"] = probability >= self.threshold
        predictions["decision_threshold"] = self.threshold
        predictions["expected_absolute_error_mm"] = error
        risk = self.config["hotspots"]
        hotspots = find_hotspots(predictions, risk["probability_threshold"]
                                 if risk["probability_threshold"] is not None else self.threshold,
                                 risk["min_cells"], risk["connectivity"])
        top_count = self.config["explanations"]["top_features"]
        records = []
        for index, row in predictions.iterrows():
            record = row.to_dict()
            for key in ("initialization_time", "valid_time"):
                record[key] = row[key].isoformat().replace("+00:00", "Z")
            record["lead_day"] = int(row.lead_day)
            record["is_bust_predicted"] = bool(row.is_bust_predicted)
            indices = np.argsort(-np.abs(contributions[index, :-1]), kind="stable")[:top_count]
            explanations = []
            for feature_index in indices:
                value = float(contributions[index, feature_index])
                explanations.append({"feature": self.features[feature_index],
                    "feature_value": float(inputs[index, feature_index]), "contribution": value,
                    "direction": "increases_model_bust_score" if value > 0 else
                                 "decreases_model_bust_score" if value < 0 else "neutral"})
            record["explanations"] = explanations
            record["explanation_base_value"] = float(contributions[index, -1])
            record["explanation_summary"] = "Factors influencing the model prediction: " + "; ".join(
                f"{item['feature']} ({item['feature_value']:.4g}) {item['direction'].replace('_', ' ')}"
                for item in explanations) + ". These are model attributions, not meteorological causes."
            records.append(record)
        summaries = []
        for lead, group in predictions.groupby("lead_day", sort=True):
            highest = group.loc[group.bust_probability.idxmax()]
            summaries.append({"lead_day": int(lead), "number_of_predictions": int(len(group)),
                "mean_bust_probability": float(group.bust_probability.mean()),
                "maximum_bust_probability": float(group.bust_probability.max()),
                "mean_confidence": float(group.confidence_score.mean()),
                "percentage_predicted_bust": float(100 * group.is_bust_predicted.mean()),
                "mean_expected_absolute_error_mm": float(group.expected_absolute_error_mm.mean()),
                "hotspot_count": sum(item["lead_day"] == lead for item in hotspots),
                "highest_risk_location": {"latitude": float(highest.latitude),
                    "longitude": float(highest.longitude), "lead_day": int(lead),
                    "bust_probability": float(highest.bust_probability)}})
        highest = predictions.loc[predictions.bust_probability.idxmax()]
        overall = {"number_of_predictions": int(len(predictions)),
            "mean_bust_probability": float(predictions.bust_probability.mean()),
            "maximum_bust_probability": float(predictions.bust_probability.max()),
            "mean_confidence": float(predictions.confidence_score.mean()),
            "percentage_predicted_bust": float(100 * predictions.is_bust_predicted.mean()),
            "mean_expected_absolute_error_mm": float(predictions.expected_absolute_error_mm.mean()),
            "hotspot_count": len(hotspots), "lead_day_count": 10,
            "grid_cell_count": int(len(predictions) // 10),
            "highest_risk_location": {"latitude": float(highest.latitude),
                "longitude": float(highest.longitude), "lead_day": int(highest.lead_day),
                "bust_probability": float(highest.bust_probability)}}
        output = {"model_id": self.model_id, "initialization_time": records[0]["initialization_time"],
                  "decision_threshold": self.threshold, "records": records, "hotspots": hotspots,
                  "lead_day_summaries": summaries, "initialization_summary": overall,
                  "metadata": {"confidence_definition": "100 * (1 - calibrated bust probability)",
                               "spread_definition": "GEFS published final six-hour interval spread, not daily spread",
                               "explanation_definition": "XGBoost TreeSHAP raw score contributions; non-causal"}}
        json.dumps(output, allow_nan=False)
        return output

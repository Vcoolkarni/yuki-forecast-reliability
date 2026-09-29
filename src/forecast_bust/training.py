from __future__ import annotations

from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from xgboost import XGBClassifier

from .features import FEATURE_COLUMNS, build_features


def temporal_split(frame: pd.DataFrame, test_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered_times = np.array(sorted(pd.to_datetime(frame["initialization_time"], utc=True).unique()))
    if len(ordered_times) < 2:
        raise ValueError("At least two initialization times are required for a leakage-safe split")
    cut = max(1, min(len(ordered_times) - 1, int(len(ordered_times) * (1 - test_fraction))))
    train_times = set(ordered_times[:cut])
    mask = pd.to_datetime(frame["initialization_time"], utc=True).isin(train_times)
    return frame.loc[mask].copy(), frame.loc[~mask].copy()


def chronological_three_way_split(frame: pd.DataFrame, validation_fraction: float, test_fraction: float):
    times = np.array(sorted(pd.to_datetime(frame["initialization_time"], utc=True).unique()))
    if len(times) < 5:
        raise ValueError("At least five initialization times are required")
    test_count = max(1, int(round(len(times) * test_fraction)))
    validation_count = max(1, int(round(len(times) * validation_fraction)))
    train_count = len(times) - validation_count - test_count
    if train_count < 2:
        raise ValueError("Split leaves fewer than two training initialization times")
    train_times = set(times[:train_count])
    validation_times = set(times[train_count:train_count + validation_count])
    test_times = set(times[train_count + validation_count:])
    series = pd.to_datetime(frame["initialization_time"], utc=True)
    return frame[series.isin(train_times)].copy(), frame[series.isin(validation_times)].copy(), frame[series.isin(test_times)].copy()


def evaluate(y_true, probability) -> dict:
    prediction = (np.asarray(probability) >= 0.5).astype(int)
    metrics = {
        "precision": precision_score(y_true, prediction, zero_division=0),
        "recall": recall_score(y_true, prediction, zero_division=0),
        "f1": f1_score(y_true, prediction, zero_division=0),
        "confusion_matrix": confusion_matrix(y_true, prediction, labels=[0, 1]).tolist(),
    }
    metrics["roc_auc"] = roc_auc_score(y_true, probability) if len(np.unique(y_true)) == 2 else None
    return metrics


def train(frame: pd.DataFrame, cfg: dict):
    featured = build_features(frame)
    train_frame, test_frame = temporal_split(featured, float(cfg["test_fraction"]))
    if train_frame["is_bust"].nunique() < 2:
        raise ValueError("Training partition must contain bust and non-bust examples")
    model = XGBClassifier(
        n_estimators=int(cfg["n_estimators"]), max_depth=int(cfg["max_depth"]),
        learning_rate=float(cfg["learning_rate"]), objective="binary:logistic",
        eval_metric="logloss", random_state=42, n_jobs=-1,
    )
    model.fit(train_frame[FEATURE_COLUMNS], train_frame["is_bust"])
    probability = model.predict_proba(test_frame[FEATURE_COLUMNS])[:, 1]
    return model, evaluate(test_frame["is_bust"], probability), test_frame, probability


def save_training_outputs(model, metrics: dict, model_path: str | Path, metrics_path: str | Path) -> None:
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    Path(metrics_path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    Path(metrics_path).write_text(json.dumps(metrics, indent=2), encoding="utf-8")


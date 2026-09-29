"""Metrics prepared for V2 experiments; no model fitting or test-set selection."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss, confusion_matrix,
                             f1_score, mean_absolute_error, mean_squared_error,
                             median_absolute_error, precision_score, recall_score, roc_auc_score)


def classification_metrics(truth, probability, threshold: float) -> dict:
    observed = np.asarray(truth, dtype=int)
    risk = np.asarray(probability, dtype=float)
    if len(observed) != len(risk) or not len(observed) or not np.isfinite(risk).all() or ((risk < 0) | (risk > 1)).any():
        raise ValueError("Bust probabilities must be aligned and in [0,1]")
    if not 0 <= threshold <= 1:
        raise ValueError("Decision threshold must be in [0,1]")
    predicted = risk >= threshold
    both = len(np.unique(observed)) == 2
    return {"precision": float(precision_score(observed, predicted, zero_division=0)),
            "recall": float(recall_score(observed, predicted, zero_division=0)),
            "f1": float(f1_score(observed, predicted, zero_division=0)),
            "roc_auc": float(roc_auc_score(observed, risk)) if both else None,
            "pr_auc": float(average_precision_score(observed, risk)) if both else None,
            "brier_score": float(brier_score_loss(observed, risk)),
            "confusion_matrix": confusion_matrix(observed, predicted, labels=[0, 1]).tolist(),
            "number_of_rows": len(observed), "bust_rate": float(observed.mean()),
            "decision_threshold": float(threshold)}


def regression_metrics(actual_absolute_error, predicted_absolute_error) -> dict:
    truth = np.asarray(actual_absolute_error, dtype=float)
    predicted = np.asarray(predicted_absolute_error, dtype=float)
    if len(truth) != len(predicted) or not len(truth) or not np.isfinite(truth).all() or not np.isfinite(predicted).all() or (truth < 0).any() or (predicted < 0).any():
        raise ValueError("Expected absolute error must be finite, nonnegative, and aligned")
    return {"mae_mm": float(mean_absolute_error(truth, predicted)),
            "rmse_mm": float(np.sqrt(mean_squared_error(truth, predicted))),
            "median_absolute_error_mm": float(median_absolute_error(truth, predicted)),
            "number_of_rows": len(truth)}


def metrics_by_lead(frame: pd.DataFrame, probability, expected_absolute_error, threshold: float) -> dict:
    if len(frame) != len(probability) or len(frame) != len(expected_absolute_error):
        raise ValueError("Per-lead predictions must align with input rows")
    result = {}
    for lead, indices in frame.groupby("lead_day").indices.items():
        group = frame.iloc[indices]
        result[str(int(lead))] = {
            "classification": classification_metrics(group.is_bust, np.asarray(probability)[indices], threshold),
            "expected_absolute_error": regression_metrics(group.target_absolute_error_mm,
                                                           np.asarray(expected_absolute_error)[indices])}
    return result

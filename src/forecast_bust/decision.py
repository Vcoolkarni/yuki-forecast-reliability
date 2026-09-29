"""Decision rules selected on validation data, independent of the test set."""
from __future__ import annotations

import numpy as np
from sklearn.metrics import precision_recall_curve


def select_validation_threshold(y_validation, probability_validation) -> dict:
    """Maximize validation F1; use the higher cutoff for exact ties.

    Call only with validation predictions after calibration has been fitted.
    The returned cutoff must then be frozen before evaluating the test set.
    """
    truth = np.asarray(y_validation)
    probability = np.asarray(probability_validation, dtype=float)
    if truth.ndim != 1 or probability.shape != truth.shape or not len(truth):
        raise ValueError("Validation labels and probabilities must be non-empty matching vectors")
    if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ValueError("Validation probabilities must be finite and within [0, 1]")
    if set(np.unique(truth)) != {0, 1}:
        raise ValueError("Validation threshold selection requires both classes")
    precision, recall, thresholds = precision_recall_curve(truth, probability)
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(2 * precision[:-1] * recall[:-1], denominator,
                   out=np.zeros_like(denominator), where=denominator > 0)
    best = np.flatnonzero(f1 == f1.max())[-1]
    return {
        "threshold": float(thresholds[best]),
        "objective": "validation_f1",
        "precision": float(precision[best]),
        "recall": float(recall[best]),
        "f1": float(f1[best]),
    }

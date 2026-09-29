import numpy as np
import pytest
from sklearn.metrics import f1_score

from forecast_bust.decision import select_validation_threshold


def test_validation_selection_recovers_busts_below_default_cutoff():
    truth = np.array([0, 0, 1, 1])
    probability = np.array([0.01, 0.05, 0.20, 0.40])
    selected = select_validation_threshold(truth, probability)
    assert selected["threshold"] == pytest.approx(0.20)
    assert selected["f1"] == 1.0
    assert f1_score(truth, probability >= 0.5, zero_division=0) == 0.0


def test_single_class_validation_cannot_select_a_bust_threshold():
    with pytest.raises(ValueError, match="both classes"):
        select_validation_threshold([0, 0], [0.1, 0.2])

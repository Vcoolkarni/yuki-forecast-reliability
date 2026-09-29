import pandas as pd
from forecast_bust.labeling import apply_percentile_labels, fit_percentile_thresholds


def test_percentile_thresholds_are_fit_from_supplied_training_rows():
    train = pd.DataFrame({"lead_day": [1, 1, 2, 2], "absolute_error": [1.0, 3.0, 10.0, 20.0]})
    thresholds = fit_percentile_thresholds(train, 50, by_lead=True)
    assert thresholds == {1: 2.0, 2: 15.0}
    labeled = apply_percentile_labels(train, thresholds)
    assert labeled["is_bust"].tolist() == [0, 1, 0, 1]

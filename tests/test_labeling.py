import pandas as pd
from forecast_bust.labeling import add_error_and_labels


def test_absolute_error_label_is_inclusive():
    frame = pd.DataFrame({"forecast_precipitation": [5.0, 30.0], "reference_precipitation": [0.0, 10.0]})
    result = add_error_and_labels(frame, {"method": "absolute_error", "bust_threshold_mm": 20})
    assert result["forecast_error"].tolist() == [5.0, 20.0]
    assert result["is_bust"].tolist() == [0, 1]


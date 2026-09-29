import pandas as pd
from forecast_bust.matching import match_forecast_reference


def test_matches_nearest_reference_time():
    forecast = pd.DataFrame({"valid_time": ["2024-07-02T00:00:00Z"], "latitude": [22.0], "longitude": [78.0], "forecast_precipitation": [12.0], "initialization_time": ["2024-07-01T00:00:00Z"], "lead_day": [1]})
    reference = pd.DataFrame({"valid_time": ["2024-07-02T00:30:00Z"], "latitude": [22.0], "longitude": [78.0], "reference_precipitation": [10.0]})
    result = match_forecast_reference(forecast, reference, 1)
    assert result.loc[0, "reference_precipitation"] == 10.0


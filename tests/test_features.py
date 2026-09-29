import pandas as pd
import numpy as np

from forecast_bust.features import FEATURE_COLUMNS, add_derived_meteorological_features, build_features


def test_derived_wind_speed_and_precipitation_gradient():
    rows = []
    for latitude in [20.0, 21.0]:
        for longitude in [76.0, 77.0]:
            rows.append({
                "initialization_time": "2026-09-01T00:00:00Z", "valid_time": "2026-09-02T00:00:00Z",
                "lead_day": 1, "latitude": latitude, "longitude": longitude,
                "forecast_precipitation": latitude + 2 * longitude,
                "forecast_u_wind_10m": 3.0, "forecast_v_wind_10m": 4.0,
            })
    result = add_derived_meteorological_features(pd.DataFrame(rows))
    assert result["forecast_wind_speed_10m"].eq(5.0).all()
    assert np.allclose(result["precipitation_gradient_mm_per_degree"], 5 ** 0.5)


def test_day_of_year_is_not_a_model_feature():
    assert "day_of_year" not in FEATURE_COLUMNS

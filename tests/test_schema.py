import pandas as pd
import pytest
from forecast_bust.schema import validate_dataset


def test_schema_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing required"):
        validate_dataset(pd.DataFrame({"lead_day": [1]}))


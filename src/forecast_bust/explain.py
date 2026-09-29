from __future__ import annotations

from pathlib import Path
import pandas as pd
import shap
from .features import FEATURE_COLUMNS


def save_shap_summary(model, frame: pd.DataFrame, output_path: str | Path, max_rows: int = 1000) -> None:
    import matplotlib.pyplot as plt
    sample = frame[FEATURE_COLUMNS].head(max_rows)
    values = shap.TreeExplainer(model).shap_values(sample)
    shap.summary_plot(values, sample, show=False)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(output_path, dpi=160, bbox_inches="tight")
    plt.close()


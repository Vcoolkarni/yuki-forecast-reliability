from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
import yaml
from matplotlib import pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
import xgboost as xgb
from xgboost import XGBClassifier

from forecast_bust.features import FEATURE_COLUMNS, build_features
from forecast_bust.decision import select_validation_threshold
from forecast_bust.labeling import apply_percentile_labels, fit_percentile_thresholds
from forecast_bust.training import chronological_three_way_split


cfg = yaml.safe_load(Path("config/phase2.yaml").read_text())
frame = pd.read_csv("data/processed/phase2_historical_fixed.csv")
frame["initialization_time"] = pd.to_datetime(frame["initialization_time"], utc=True)
train_raw, validation_raw, test_raw = chronological_three_way_split(
    frame, cfg["model"]["validation_fraction"], cfg["model"]["test_fraction"]
)

percentile = float(cfg["labeling"]["percentile"])
global_threshold = fit_percentile_thresholds(train_raw, percentile, by_lead=False)
lead_thresholds = fit_percentile_thresholds(train_raw, percentile, by_lead=True)


def distribution(data, label):
    counts = data[label].value_counts().reindex([0, 1], fill_value=0)
    return {"no_bust": int(counts[0]), "bust": int(counts[1]), "bust_rate": float(data[label].mean())}


variants = {}
for split_name, split in (("train", train_raw), ("validation", validation_raw), ("test", test_raw), ("all", frame)):
    fixed = split.copy()
    global_labeled = apply_percentile_labels(split, global_threshold)
    lead_labeled = apply_percentile_labels(split, lead_thresholds)
    variants[split_name] = {
        "fixed_20mm": distribution(fixed, "is_bust"),
        "training_global_percentile": distribution(global_labeled, "is_bust"),
        "training_lead_specific_percentile": distribution(lead_labeled, "is_bust"),
        "lead_specific_distribution_by_lead": {
            str(int(lead)): distribution(group, "is_bust")
            for lead, group in lead_labeled.groupby("lead_day")
        },
    }

train = build_features(apply_percentile_labels(train_raw, lead_thresholds))
validation = build_features(apply_percentile_labels(validation_raw, lead_thresholds))
test = build_features(apply_percentile_labels(test_raw, lead_thresholds))
negative, positive = train["is_bust"].value_counts().reindex([0, 1], fill_value=0)
if positive == 0 or negative == 0:
    raise ValueError("Training labels must contain both classes")
if validation["is_bust"].nunique() != 2:
    raise ValueError("Platt calibration and threshold selection require both validation classes")

model = XGBClassifier(
    n_estimators=int(cfg["model"]["n_estimators"]),
    max_depth=int(cfg["model"]["max_depth"]),
    learning_rate=float(cfg["model"]["learning_rate"]),
    objective="binary:logistic",
    eval_metric="logloss",
    scale_pos_weight=float(negative / positive),
    subsample=0.9,
    colsample_bytree=0.9,
    random_state=int(cfg["project"]["random_seed"]),
    n_jobs=-1,
)
model.fit(train[FEATURE_COLUMNS], train["is_bust"], eval_set=[(validation[FEATURE_COLUMNS], validation["is_bust"])], verbose=False)

validation_probability = np.clip(model.predict_proba(validation[FEATURE_COLUMNS])[:, 1], 1e-6, 1 - 1e-6)
calibrator = LogisticRegression(random_state=int(cfg["project"]["random_seed"]))
calibrator.fit(np.log(validation_probability / (1 - validation_probability)).reshape(-1, 1), validation["is_bust"])


def calibrated_probability(data):
    raw = np.clip(model.predict_proba(data[FEATURE_COLUMNS])[:, 1], 1e-6, 1 - 1e-6)
    return calibrator.predict_proba(np.log(raw / (1 - raw)).reshape(-1, 1))[:, 1]


def metrics(data, probability, threshold=0.5):
    truth = data["is_bust"].to_numpy()
    predicted = (probability >= threshold).astype(int)
    return {
        "precision": float(precision_score(truth, predicted, zero_division=0)),
        "recall": float(recall_score(truth, predicted, zero_division=0)),
        "f1": float(f1_score(truth, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(truth, probability)) if len(np.unique(truth)) == 2 else None,
        "brier_score": float(brier_score_loss(truth, probability)),
        "confusion_matrix": confusion_matrix(truth, predicted, labels=[0, 1]).tolist(),
        "class_distribution": distribution(data, "is_bust"),
        "decision_threshold": float(threshold),
    }


# Select exclusively on validation; freeze the decision rule before test inference.
calibrated_validation_probability = calibrated_probability(validation)
threshold_selection = select_validation_threshold(validation["is_bust"], calibrated_validation_probability)
decision_threshold = threshold_selection["threshold"]
validation_diagnostics = {
    "raw_at_0_5": metrics(validation, validation_probability),
    "calibrated_at_0_5": metrics(validation, calibrated_validation_probability),
    "calibrated_at_selected_threshold": metrics(validation, calibrated_validation_probability, decision_threshold),
    "by_lead_day": {
        str(int(lead)): metrics(group, calibrated_validation_probability[group.index.to_numpy()], decision_threshold)
        for lead, group in validation.reset_index(drop=True).groupby("lead_day")
    },
    "note": "Validation is used for calibration and threshold selection; these metrics are selection diagnostics, not unbiased performance estimates.",
}
test_probability = calibrated_probability(test)
results = metrics(test, test_probability, decision_threshold)
results["threshold_selection"] = threshold_selection
results["validation_diagnostics"] = validation_diagnostics
results["calibration"] = {
    "method": "Platt logistic regression on validation logits",
    "slope": float(calibrator.coef_[0, 0]),
    "intercept": float(calibrator.intercept_[0]),
    "class_weight": None,
}
results["scale_pos_weight"] = float(negative / positive)
test_by_lead = test.reset_index(drop=True)
results["by_lead_day"] = {
    str(int(lead)): metrics(group, test_probability[group.index.to_numpy()], decision_threshold)
    for lead, group in test_by_lead.groupby("lead_day")
}
results["split_initializations"] = {
    "train": sorted(x.isoformat() for x in train_raw.initialization_time.unique()),
    "validation": sorted(x.isoformat() for x in validation_raw.initialization_time.unique()),
    "test": sorted(x.isoformat() for x in test_raw.initialization_time.unique()),
}
results["label_definition"] = {
    "type": "training_lead_specific_percentile",
    "percentile": percentile,
    "thresholds_mm": {str(key): value for key, value in lead_thresholds.items()},
}

Path("reports").mkdir(exist_ok=True)
Path("models").mkdir(exist_ok=True)
Path("reports/phase2_class_distributions.json").write_text(json.dumps({"global_threshold_mm": global_threshold["global"], "lead_thresholds_mm": lead_thresholds, "distributions": variants}, indent=2), encoding="utf-8")
Path("reports/phase2_metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
prediction_output = test_raw.copy()
prediction_output["is_bust"] = test["is_bust"].to_numpy()
prediction_output["bust_probability"] = test_probability
prediction_output["forecast_confidence"] = 1 - test_probability
prediction_output["predicted_is_bust"] = (test_probability >= decision_threshold).astype("int8")
prediction_output.to_csv("reports/phase2_test_predictions.csv", index=False)
joblib.dump({"model": model, "calibrator": calibrator, "features": FEATURE_COLUMNS, "label_thresholds": lead_thresholds, "decision_threshold": decision_threshold, "threshold_selection": threshold_selection}, "models/phase2_xgboost_calibrated.joblib")

try:
    import shap
    sample = test[FEATURE_COLUMNS].sample(min(2000, len(test)), random_state=42)
    values = shap.TreeExplainer(model).shap_values(sample)
    shap.summary_plot(values, sample, show=False)
    plt.tight_layout()
    plt.savefig("reports/phase2_shap_summary.png", dpi=160, bbox_inches="tight")
    plt.close()
    results["shap_status"] = "generated"
except Exception as error:
    sample = test[FEATURE_COLUMNS].sample(min(2000, len(test)), random_state=42)
    contributions = model.get_booster().predict(xgb.DMatrix(sample), pred_contribs=True)
    importance = pd.Series(np.abs(contributions[:, :-1]).mean(axis=0), index=FEATURE_COLUMNS).sort_values()
    importance.plot.barh()
    plt.xlabel("mean |SHAP value|")
    plt.tight_layout()
    plt.savefig("reports/phase2_shap_summary.png", dpi=160, bbox_inches="tight")
    plt.close()
    results["shap_status"] = f"generated via XGBoost pred_contribs (Python SHAP unavailable: {type(error).__name__})"
Path("reports/phase2_metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results))

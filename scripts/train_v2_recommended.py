"""Train and evaluate V2 RECOMMENDED once, with 2025 held out until frozen."""

from forecast_bust.v2.budget_planning import load_budget_config
from forecast_bust.v2.configuration import load_v2_config
from forecast_bust.v2.recommended_training import train_recommended


if __name__ == "__main__":
    result = train_recommended(load_v2_config(), load_budget_config())
    print("V2_FINAL_TEST_PR_AUC=" + str(result["classification"]["pr_auc"]))
    print("V2_FINAL_TEST_ROC_AUC=" + str(result["classification"]["roc_auc"]))
    print("V2_FINAL_TEST_F1=" + str(result["classification"]["f1"]))

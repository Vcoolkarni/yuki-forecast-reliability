"""Offline, deterministic regional reliability text from inference only."""


def create_brief(artifact: dict, lead_day: int) -> dict:
    day = next((item for item in artifact["lead_day_summaries"] if item["lead_day"] == lead_day), None)
    if day is None:
        raise ValueError("Requested forecast lead is unavailable")
    records = [item for item in artifact["records"] if item["lead_day"] == lead_day]
    highest = max(records, key=lambda item: item["bust_probability"])
    categories = {"High": 0, "Moderate": 0, "Low": 0}
    for item in records:
        categories[item["confidence_category"]] += 1
    category = max(categories, key=categories.get)
    features = [item["feature"] for item in highest["explanations"]]
    location = f"{highest['latitude']:.2f}°N, {highest['longitude']:.2f}°E"
    hotspot_count = day["hotspot_count"]
    text = (f"DAY {lead_day} RELIABILITY BRIEF — Mean model-derived confidence is {day['mean_confidence']:.1f}% "
            f"({category} is the most common grid-cell category). {hotspot_count} elevated-risk "
            f"hotspot{'s' if hotspot_count != 1 else ''} detected. Highest bust probability is "
            f"{highest['bust_probability'] * 100:.1f}% at {location}. "
            f"The leading model contributions there are {', '.join(features) if features else 'unavailable'}. ")
    caveat = ("Model-derived forecast reliability guidance, not a calibrated meteorological probability of "
              "correctness. TreeSHAP contributions influence the model prediction, not physical causality. "
              "Interpret alongside the underlying NWP forecast.")
    return {"initialization_time": artifact["initialization_time"], "lead_day": lead_day,
            "confidence_category": category, "mean_confidence": day["mean_confidence"],
            "mean_bust_probability": day["mean_bust_probability"], "hotspot_count": hotspot_count,
            "highest_risk_location": day["highest_risk_location"], "contributing_features": features,
            "text": text, "caveat": caveat}

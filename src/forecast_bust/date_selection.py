from __future__ import annotations

from datetime import date


def configured_initialization_dates(config: dict) -> list[str]:
    """Return the explicit, ordered Phase 2 initialization-date selection."""
    values = config.get("time", {}).get("initialization_dates")
    if not isinstance(values, list) or not values:
        raise ValueError("time.initialization_dates must be a non-empty explicit list of YYYY-MM-DD dates")
    normalized = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Each time.initialization_dates entry must be a quoted YYYY-MM-DD string")
        try:
            normalized.append(date.fromisoformat(value).isoformat())
        except ValueError as error:
            raise ValueError(f"Invalid initialization date {value!r}; expected YYYY-MM-DD") from error
    if len(set(normalized)) != len(normalized):
        raise ValueError("time.initialization_dates contains duplicate dates")
    if normalized != sorted(normalized):
        raise ValueError("time.initialization_dates must be in chronological order")
    return normalized

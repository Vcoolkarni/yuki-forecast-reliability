"""V2-only API surface; V1 endpoints and defaults remain independent."""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from .brief import create_brief
from .comparison import compare_runs
from .models import V2DayResponse, V2GridCell, V2StateDay
from .repository import normalize_initialization
from .v2_repository import V2Repository
from .v2_analogs import V2AnalogRepository

Lead = Annotated[int, Path(ge=1, le=10)]


def state_metrics(artifact: dict, name: str, members: set[tuple[float, float]], lead: int) -> dict:
    rows = [item for item in artifact["records"] if item["lead_day"] == lead
            and (item["latitude"], item["longitude"]) in members]
    if not rows:
        raise HTTPException(409, "This state/UT has no co-located 0.5-degree grid center; no state forecast is inferred")
    highest = max(rows, key=lambda item: item["bust_probability"])
    hotspots = [item for item in artifact["hotspots"] if item["lead_day"] == lead and any(
        (cell["latitude"], cell["longitude"]) in members for cell in item["member_cells"])]
    return {"state": name, "lead_day": lead, "grid_cell_count": len(rows),
            "coverage": "grid_centers_inside_state_polygon", "mean_forecast_confidence":
            sum(item["confidence_score"] for item in rows) / len(rows),
            "mean_bust_probability": sum(item["bust_probability"] for item in rows) / len(rows),
            "predicted_bust_cell_percentage": 100 * sum(item["is_bust_predicted"] for item in rows) / len(rows),
            "mean_expected_absolute_error_mm": sum(item["expected_absolute_error_mm"] for item in rows) / len(rows),
            "mean_gefs_end_window_spread_6h_mm": sum(item["gefs_end_window_spread_6h_mm"] for item in rows) / len(rows),
            "highest_risk_cell": highest, "hotspot_count": len(hotspots)}


def create_v2_router(store: V2Repository) -> APIRouter:
    router = APIRouter(prefix="/api/v2")
    packaged_analogs = store.project_root / "runtime/analogs_v2"
    analog_store = V2AnalogRepository(packaged_analogs if packaged_analogs.is_dir() else
                                      store.project_root / "data/processed/v2/recommended_0p50")

    def ready():
        try:
            store.initialize()
        except (OSError, ValueError, KeyError) as error:
            raise HTTPException(503, f"V2 model or forecast-only feed is unavailable ({type(error).__name__})") from error

    def forecast(initialization: str):
        ready()
        try:
            return store.get(initialization)
        except KeyError as error:
            raise HTTPException(404, "V2 initialization is unavailable; see /api/v2/health") from error
        except ValueError as error:
            try:
                normalize_initialization(initialization)
            except ValueError as invalid:
                raise HTTPException(422, str(invalid)) from invalid
            raise HTTPException(503, "V2 forecast input is incompatible with the frozen model") from error

    def day(artifact, lead):
        return [item for item in artifact["records"] if item["lead_day"] == lead]

    def members(name):
        ready()
        if name not in store.membership:
            raise HTTPException(404, "Unknown India state/UT")
        return store.membership[name]

    @router.get("/health")
    def health():
        ready()
        return store.health()

    @router.get("/states")
    def states():
        ready()
        return {"boundary_source": "geoBoundaries IND ADM1 release 9469f09, CC BY 2.5 IN",
                "grid_resolution_degrees": 0.5,
                "states": [{"name": name, "grid_cell_count": len(cells),
                            "has_grid_centers": bool(cells)} for name, cells in sorted(store.membership.items())]}

    @router.get("/runs/{initialization}/metadata")
    def run_metadata(initialization: str):
        ready()
        try:
            return store.run_metadata(initialization)
        except KeyError as error:
            raise HTTPException(404, "V2 initialization is unavailable") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @router.get("/forecast/{initialization}/summary")
    def summary(initialization: str):
        artifact = forecast(initialization)
        result = {key: artifact[key] for key in ("initialization_time", "model_id", "decision_threshold",
                                                "initialization_summary", "lead_day_summaries", "metadata")}
        result["run_kind"] = store.run_metadata(initialization)["source_kind"]
        return result

    @router.get("/forecast/{initialization}/day/{lead_day}", response_model=V2DayResponse)
    def grid(initialization: str, lead_day: Lead):
        artifact = forecast(initialization)
        return {"initialization_time": artifact["initialization_time"], "lead_day": lead_day,
                "records": day(artifact, lead_day), "source_kind": store.run_metadata(initialization)["source_kind"]}

    @router.get("/forecast/{initialization}/day/{lead_day}/hotspots")
    def hotspots(initialization: str, lead_day: Lead):
        artifact = forecast(initialization)
        return {"initialization_time": artifact["initialization_time"], "lead_day": lead_day,
                "hotspots": [item for item in artifact["hotspots"] if item["lead_day"] == lead_day]}

    @router.get("/forecast/{initialization}/day/{lead_day}/highest-risk", response_model=V2GridCell)
    def highest(initialization: str, lead_day: Lead):
        return max(day(forecast(initialization), lead_day), key=lambda item: item["bust_probability"])

    @router.get("/forecast/{initialization}/cell", response_model=V2GridCell)
    def cell(initialization: str, latitude: Annotated[float, Query(ge=-90, le=90)],
             longitude: Annotated[float, Query(ge=-180, le=180)],
             lead_day: Annotated[int, Query(ge=1, le=10)]):
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise HTTPException(422, "Coordinates must be finite")
        for item in day(forecast(initialization), lead_day):
            if math.isclose(item["latitude"], latitude, abs_tol=1e-8) and math.isclose(
                    item["longitude"], longitude, abs_tol=1e-8):
                return item
        raise HTTPException(404, "Coordinates are not a V2 grid center")

    @router.get("/forecast/{initialization}/cell/analogs")
    def analogs(initialization: str, latitude: Annotated[float, Query(ge=-90, le=90)],
                longitude: Annotated[float, Query(ge=-180, le=180)],
                lead_day: Annotated[int, Query(ge=1, le=10)],
                limit: Annotated[int, Query(ge=1, le=5)] = 5):
        selected = cell(initialization, latitude, longitude, lead_day)
        try:
            return analog_store.retrieve(selected, limit)
        except (OSError, ValueError) as error:
            raise HTTPException(503, "V2 training-only analog archive is unavailable") from error

    @router.get("/forecast/{initialization}/cell/explainability")
    def explainability(initialization: str, latitude: Annotated[float, Query(ge=-90, le=90)],
                       longitude: Annotated[float, Query(ge=-180, le=180)],
                       lead_day: Annotated[int, Query(ge=1, le=10)]):
        selected = cell(initialization, latitude, longitude, lead_day)
        return {key: selected[key] for key in ("initialization_time", "lead_day", "latitude", "longitude",
            "bust_probability", "explanations", "explanation_summary", "explanation_base_value")}

    @router.get("/forecast/{initialization}/timeline")
    def timeline(initialization: str):
        artifact = forecast(initialization)
        return {"initialization_time": artifact["initialization_time"], "days": artifact["lead_day_summaries"]}

    @router.get("/forecast/{initialization}/day/{lead_day}/expected-error")
    def expected_error(initialization: str, lead_day: Lead):
        rows = day(forecast(initialization), lead_day)
        return {"lead_day": lead_day, "units": "mm", "cells": [
            {"latitude": item["latitude"], "longitude": item["longitude"],
             "expected_absolute_error_mm": item["expected_absolute_error_mm"]} for item in rows]}

    @router.get("/forecast/{initialization}/day/{lead_day}/gefs-uncertainty")
    def gefs_uncertainty(initialization: str, lead_day: Lead):
        rows = day(forecast(initialization), lead_day)
        return {"lead_day": lead_day,
                "spread_definition": "Published GEFS spread for the final six-hour interval; not daily spread",
                "cells": [{"latitude": item["latitude"], "longitude": item["longitude"],
                           "gefs_precipitation_mean_mm": item["gefs_precipitation_mean_mm"],
                           "gefs_end_window_spread_6h_mm": item["gefs_end_window_spread_6h_mm"]}
                          for item in rows]}

    @router.get("/forecast/{initialization}/day/{lead_day}/brief")
    def brief(initialization: str, lead_day: Lead):
        return create_brief(forecast(initialization), lead_day)

    @router.get("/forecast/{initialization}/state/{state}/day/{lead_day}", response_model=V2StateDay)
    def state_day(initialization: str, state: str, lead_day: Lead):
        artifact = forecast(initialization)
        return state_metrics(artifact, state, members(state), lead_day)

    @router.get("/forecast/{initialization}/state/{state}/timeline")
    def state_timeline(initialization: str, state: str):
        artifact = forecast(initialization)
        selected = members(state)
        return {"state": state, "initialization_time": artifact["initialization_time"],
                "days": [{key: value for key, value in state_metrics(artifact, state, selected, lead).items()
                          if key != "highest_risk_cell"} for lead in range(1, 11)]}

    @router.get("/forecast/{initialization}/state/{state}/summary")
    def state_summary(initialization: str, state: str):
        artifact = forecast(initialization)
        selected = members(state)
        days = [state_metrics(artifact, state, selected, lead) for lead in range(1, 11)]
        most_risky = max(days, key=lambda item: item["mean_bust_probability"])
        return {"state": state, "initialization_time": artifact["initialization_time"],
                "grid_cell_count": len(selected), "coverage": "grid_centers_inside_state_polygon",
                "most_uncertain_lead_day": most_risky["lead_day"], "days": days}

    @router.get("/forecast/{initialization}/state/{state}/day/{lead_day}/brief")
    def state_brief(initialization: str, state: str, lead_day: Lead):
        data = state_metrics(forecast(initialization), state, members(state), lead_day)
        return {"state": state, "lead_day": lead_day, "mean_confidence": data["mean_forecast_confidence"],
                "mean_bust_probability": data["mean_bust_probability"],
                "hotspot_count": data["hotspot_count"], "highest_risk_location": data["highest_risk_cell"],
                "text": f"{state}: Day {lead_day} mean model-derived confidence is {data['mean_forecast_confidence']:.1f}% "
                        f"across {data['grid_cell_count']} co-located grid cells; predicted bust-cell percentage is "
                        f"{data['predicted_bust_cell_percentage']:.1f}%. Mean predicted absolute error is "
                        f"{data['mean_expected_absolute_error_mm']:.1f} mm.",
                "caveat": "State aggregation of grid-cell predictions, not a uniform state forecast or observed error."}

    @router.get("/compare")
    def comparison(current_initialization: str, previous_initialization: str,
                   lead_day: Annotated[int, Query(ge=1, le=10)]):
        ready()
        try:
            compatible = store.comparison_compatible(current_initialization, previous_initialization)
        except KeyError as error:
            raise HTTPException(404, "V2 initialization is unavailable") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not compatible:
            raise HTTPException(422, "Run comparison requires the same forecast source kind, model and grid")
        current, previous = forecast(current_initialization), forecast(previous_initialization)
        if current["initialization_time"] <= previous["initialization_time"]:
            raise HTTPException(422, "Current initialization must be later than previous")
        return compare_runs(current, previous, lead_day)

    @router.get("/forecast/{initialization}/day/{lead_day}/escalation")
    def escalation(initialization: str, lead_day: Lead, previous_initialization: str):
        ready()
        try:
            compatible = store.comparison_compatible(initialization, previous_initialization)
        except KeyError as error:
            raise HTTPException(404, "V2 initialization is unavailable") from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        if not compatible:
            raise HTTPException(422, "Escalation requires comparable runs from the same source kind, model and grid")
        current, previous = forecast(initialization), forecast(previous_initialization)
        if current["initialization_time"] <= previous["initialization_time"]:
            raise HTTPException(422, "Previous initialization must be earlier")
        result = compare_runs(current, previous, lead_day)
        return {"initialization_time": current["initialization_time"], "lead_day": lead_day,
                "previous_initialization": previous["initialization_time"],
                "emerging_bust_cells": result["emerging_bust_cells"],
                "resolved_bust_cells": result["resolved_bust_cells"],
                "new_hotspot_regions": result["new_hotspot_regions"],
                "largest_risk_increases": result["largest_risk_increases"],
                "provenance": "Change in model predictions between two runs, not observed forecast error."}

    @router.get("/forecast/{initialization}/variables/trend")
    def variable_trend(initialization: str, field: str):
        artifact = forecast(initialization)
        allowed = set(store.service.features) - {"lead_day"}
        if field not in allowed and field != "expected_absolute_error_mm":
            raise HTTPException(422, "Unsupported V2 forecast field")
        return {"initialization_time": artifact["initialization_time"], "field": field,
                "days": [{"lead_day": lead, "value": sum(item[field] for item in day(artifact, lead)) / len(day(artifact, lead))}
                         for lead in range(1, 11)]}

    return router

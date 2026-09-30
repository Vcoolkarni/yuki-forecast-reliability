from contextlib import asynccontextmanager
from typing import Annotated, Literal
import logging
import math
import os

from fastapi import FastAPI, HTTPException, Path, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .analogs import AnalogRepository
from .brief import create_brief
from .comparison import compare_runs
from .models import (AnalogsResponse, BriefResponse, ComparisonResponse, DayResponse, GridCell,
                     HealthResponse, HotspotsResponse, SummaryResponse, TimelinePoint,
                     TimelineResponse, VariableTrendResponse)
from .repository import ForecastRepository
from .settings import APISettings, PROJECT_ROOT
from .v2_repository import V2Repository
from .v2_routes import create_v2_router

LeadPath = Annotated[int, Path(ge=1, le=10)]
logger = logging.getLogger(__name__)


def create_app(settings: APISettings | None = None, repository=None) -> FastAPI:
    settings = settings or APISettings.load()
    store = repository if repository is not None else ForecastRepository(settings)
    analog_store = AnalogRepository(settings.historical_path)

    @asynccontextmanager
    async def lifespan(application):
        try:
            store.initialize()
        except Exception as error:
            # Only log the error type; do not expose local paths or source contents.
            logger.error("API model/forecast initialization failed: %s", type(error).__name__)
        yield

    application = FastAPI(title="Forecast Bust API", version="1.0.0", lifespan=lifespan)
    application.state.repository = store
    application.state.analogs = analog_store
    # V2 is registered independently; V1 startup/readiness remains unchanged.
    # Keep only one full-grid artifact resident on memory-constrained hosts.
    v2_cache_size = int(os.environ.get("FORECAST_BUST_V2_CACHE_SIZE", "4"))
    if v2_cache_size < 1:
        raise ValueError("FORECAST_BUST_V2_CACHE_SIZE must be positive")
    v2_store = V2Repository(PROJECT_ROOT, cache_size=v2_cache_size)
    application.state.v2_repository = v2_store
    application.include_router(create_v2_router(v2_store))
    # Forecast-grid JSON is large; HTTP compression changes transfer size, not model outputs.
    application.add_middleware(GZipMiddleware, minimum_size=1000)
    application.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                               allow_credentials=False, allow_methods=["GET"], allow_headers=["Accept", "Content-Type"])

    def forecast(initialization):
        try:
            return store.get(initialization)
        except KeyError:
            raise HTTPException(404, "Forecast initialization is unavailable; see /health for available initializations")
        except ValueError as error:
            # Date syntax errors are client errors; inference validation failures indicate server readiness.
            from .repository import normalize_initialization
            try:
                normalize_initialization(initialization)
            except ValueError as date_error:
                raise HTTPException(422, str(date_error)) from date_error
            logger.error("Forecast inference validation failed: %s", type(error).__name__)
            raise HTTPException(503, "Forecast input is incompatible with the loaded inference service") from error
        except RuntimeError as error:
            raise HTTPException(503, "Model/forecast source is not ready; check /health") from error

    def day_records(artifact, lead):
        records = [record for record in artifact["records"] if record["lead_day"] == lead]
        if not records:
            raise HTTPException(404, "Requested forecast lead is unavailable")
        return records

    def find_cell(initialization, latitude, longitude, lead_day):
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise HTTPException(422, "Coordinates must be finite")
        records = day_records(forecast(initialization), lead_day)
        matches = [record for record in records if math.isclose(record["latitude"], latitude, rel_tol=0, abs_tol=1e-8)
                   and math.isclose(record["longitude"], longitude, rel_tol=0, abs_tol=1e-8)]
        if not matches:
            raise HTTPException(404, "Coordinates do not identify an available grid cell; use coordinates from the day endpoint")
        return matches[0]

    @application.get("/health", response_model=HealthResponse)
    def health(response: Response):
        result = store.health()
        if result["status"] != "ready":
            response.status_code = 503
        return result

    @application.get("/api/v1/forecast/{initialization}/summary", response_model=SummaryResponse)
    def summary(initialization: str):
        artifact = forecast(initialization)
        return {key: artifact[key] for key in ("initialization_time", "model_id", "decision_threshold",
                                               "initialization_summary", "lead_day_summaries")}

    @application.get("/api/v1/forecast/{initialization}/day/{lead_day}", response_model=DayResponse)
    def day(initialization: str, lead_day: LeadPath):
        artifact = forecast(initialization)
        return {"initialization_time": artifact["initialization_time"], "lead_day": lead_day,
                "records": day_records(artifact, lead_day)}

    @application.get("/api/v1/forecast/{initialization}/day/{lead_day}/hotspots", response_model=HotspotsResponse)
    def hotspots(initialization: str, lead_day: LeadPath):
        artifact = forecast(initialization)
        day_records(artifact, lead_day)
        return {"initialization_time": artifact["initialization_time"], "lead_day": lead_day,
                "hotspots": [item for item in artifact["hotspots"] if item["lead_day"] == lead_day]}

    @application.get("/api/v1/forecast/{initialization}/day/{lead_day}/highest-risk", response_model=GridCell)
    def highest_risk(initialization: str, lead_day: LeadPath):
        return max(day_records(forecast(initialization), lead_day), key=lambda record: record["bust_probability"])

    @application.get("/api/v1/forecast/{initialization}/cell", response_model=GridCell)
    def cell(initialization: str, latitude: Annotated[float, Query(ge=-90, le=90)],
             longitude: Annotated[float, Query(ge=-180, le=180)], lead_day: Annotated[int, Query(ge=1, le=10)]):
        return find_cell(initialization, latitude, longitude, lead_day)

    @application.get("/api/v1/forecast/{initialization}/cell/analogs", response_model=AnalogsResponse)
    def analogs(initialization: str, latitude: Annotated[float, Query(ge=-90, le=90)],
                longitude: Annotated[float, Query(ge=-180, le=180)],
                lead_day: Annotated[int, Query(ge=1, le=10)], limit: Annotated[int, Query(ge=1, le=5)] = 5):
        selected = find_cell(initialization, latitude, longitude, lead_day)
        try:
            return analog_store.retrieve(selected, limit)
        except (OSError, ValueError) as error:
            logger.error("Historical analog source unavailable: %s", type(error).__name__)
            raise HTTPException(503, "Historical analog source is unavailable or incompatible") from error

    @application.get("/api/v1/forecast/{initialization}/timeline", response_model=TimelineResponse)
    def timeline(initialization: str):
        artifact = forecast(initialization)
        return {"initialization_time": artifact["initialization_time"],
                "days": [{key: day[key] for key in TimelinePoint.model_fields} for day in artifact["lead_day_summaries"]]}

    @application.get("/api/v1/forecast/{initialization}/day/{lead_day}/brief", response_model=BriefResponse)
    def brief(initialization: str, lead_day: LeadPath):
        return create_brief(forecast(initialization), lead_day)

    @application.get("/api/v1/compare", response_model=ComparisonResponse)
    def compare(current_initialization: str, previous_initialization: str,
                lead_day: Annotated[int, Query(ge=1, le=10)]):
        current, previous = forecast(current_initialization), forecast(previous_initialization)
        if current["initialization_time"] <= previous["initialization_time"]:
            raise HTTPException(422, "Current initialization must be later than previous initialization")
        try:
            return compare_runs(current, previous, lead_day)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    ForecastField = Literal["forecast_precipitation", "forecast_temperature_2m", "forecast_relative_humidity_2m",
                            "forecast_mean_sea_level_pressure", "forecast_u_wind_10m", "forecast_v_wind_10m",
                            "forecast_wind_speed_10m", "precipitation_gradient_mm_per_degree"]

    @application.get("/api/v1/forecast/{initialization}/variables/trend", response_model=VariableTrendResponse)
    def variable_trend(initialization: str, field: ForecastField):
        artifact = forecast(initialization)
        days = []
        for lead in range(1, 11):
            records = day_records(artifact, lead)
            days.append({"lead_day": lead, "value": sum(item[field] for item in records) / len(records)})
        return {"initialization_time": artifact["initialization_time"], "field": field, "days": days}

    return application


app = create_app()

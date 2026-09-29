from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Confidence = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Lead = Annotated[int, Field(ge=1, le=10)]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Contribution(APIModel):
    feature: str
    feature_value: float
    contribution: float
    direction: Literal["increases_model_bust_score", "decreases_model_bust_score", "neutral"]


class GridCell(APIModel):
    initialization_time: str
    valid_time: str
    lead_day: Lead
    latitude: float
    longitude: float
    forecast_precipitation: float
    forecast_temperature_2m: float
    forecast_relative_humidity_2m: float
    forecast_mean_sea_level_pressure: float
    forecast_u_wind_10m: float
    forecast_v_wind_10m: float
    forecast_wind_speed_10m: float
    precipitation_gradient_mm_per_degree: float
    bust_probability: Probability
    confidence_score: Confidence
    confidence_category: Literal["High", "Moderate", "Low"]
    is_bust_predicted: bool
    decision_threshold: Probability
    explanations: list[Contribution]
    explanation_summary: str
    explanation_base_value: float


class RiskLocation(APIModel):
    latitude: float
    longitude: float
    lead_day: Lead
    bust_probability: Probability


class Summary(APIModel):
    number_of_predictions: int
    mean_bust_probability: Probability
    maximum_bust_probability: Probability
    mean_confidence: Confidence
    percentage_predicted_bust: Confidence
    highest_risk_location: RiskLocation
    hotspot_count: int


class DaySummary(Summary):
    lead_day: Lead


class InitializationSummary(Summary):
    lead_day_count: int
    grid_cell_count: int


class SummaryResponse(APIModel):
    initialization_time: str
    model_id: str | None
    decision_threshold: Probability
    initialization_summary: InitializationSummary
    lead_day_summaries: list[DaySummary]


class DayResponse(APIModel):
    initialization_time: str
    lead_day: Lead
    records: list[GridCell]


class BoundingBox(APIModel):
    south: float
    north: float
    west: float
    east: float


class Hotspot(APIModel):
    hotspot_id: str
    lead_day: Lead
    number_of_cells: int
    centroid_latitude: float
    centroid_longitude: float
    mean_bust_probability: Probability
    max_bust_probability: Probability
    mean_confidence: Confidence
    member_cells: list["GridCoordinate"]
    bounding_box: BoundingBox


class GridCoordinate(APIModel):
    latitude: float
    longitude: float


class HotspotsResponse(APIModel):
    initialization_time: str
    lead_day: Lead
    hotspots: list[Hotspot]


class TimelinePoint(APIModel):
    lead_day: Lead
    mean_bust_probability: Probability
    maximum_bust_probability: Probability
    mean_confidence: Confidence
    percentage_predicted_bust: Confidence
    hotspot_count: int


class TimelineResponse(APIModel):
    initialization_time: str
    days: list[TimelinePoint]


class HealthResponse(APIModel):
    api_ready: bool
    model_ready: bool
    forecast_ready: bool
    status: Literal["ready", "not_ready"]
    model_id: str | None
    decision_threshold: Probability | None
    features: list[str]
    available_initializations: list[str]
    cached_initializations: int
    grid: "GridMetadata | None" = None


class GridMetadata(APIModel):
    south: float
    north: float
    west: float
    east: float
    latitude_step_degrees: float | None
    longitude_step_degrees: float | None


class ComparisonCell(APIModel):
    latitude: float
    longitude: float
    lead_day: Lead
    previous_bust_probability: Probability
    current_bust_probability: Probability
    delta_bust_probability: float
    previous_confidence: Confidence
    current_confidence: Confidence
    delta_confidence: float
    state: Literal["emerging", "resolved", "persistent", "neither"]


class ComparisonResponse(APIModel):
    current_initialization: str
    previous_initialization: str
    lead_day: Lead
    number_of_cells: int
    mean_probability_delta: float
    mean_confidence_delta: float
    emerging_bust_cells: int
    resolved_bust_cells: int
    persistent_bust_cells: int
    previous_hotspot_count: int
    current_hotspot_count: int
    hotspot_count_delta: int
    new_hotspot_regions: int
    resolved_hotspot_regions: int
    largest_risk_increases: list[ComparisonCell]
    largest_risk_decreases: list[ComparisonCell]
    cells: list[ComparisonCell]


class Analog(APIModel):
    initialization_time: str
    lead_day: Lead
    latitude: float
    longitude: float
    similarity_score: Probability
    distance: Annotated[float, Field(ge=0)]
    forecast_precipitation: float
    reference_precipitation: float
    absolute_error: Annotated[float, Field(ge=0)]
    is_bust: bool


class AnalogsResponse(APIModel):
    initialization_time: str
    latitude: float
    longitude: float
    lead_day: Lead
    number_of_analogs: int
    percentage_busted: Confidence | None
    mean_historical_absolute_error: float | None
    analogs: list[Analog]
    provenance: str


class BriefResponse(APIModel):
    initialization_time: str
    lead_day: Lead
    confidence_category: Literal["High", "Moderate", "Low"]
    mean_confidence: Confidence
    mean_bust_probability: Probability
    hotspot_count: int
    highest_risk_location: RiskLocation
    contributing_features: list[str]
    text: str
    caveat: str


class VariableTrendPoint(APIModel):
    lead_day: Lead
    value: float


class VariableTrendResponse(APIModel):
    initialization_time: str
    field: str
    days: list[VariableTrendPoint]


class V2GridCell(GridCell):
    forecast_precipitable_water: float
    forecast_cape_surface: float
    gefs_precipitation_mean_mm: float
    gefs_end_window_spread_6h_mm: float
    gfs_minus_gefs_mean_precipitation_mm: float
    expected_absolute_error_mm: Annotated[float, Field(ge=0)]


class V2DayResponse(APIModel):
    initialization_time: str
    lead_day: Lead
    records: list[V2GridCell]
    source_kind: Literal["historical_demo", "forecast_only_feed", "current_forecast"]


class V2StateDay(APIModel):
    state: str
    lead_day: Lead
    grid_cell_count: int
    coverage: Literal["grid_centers_inside_state_polygon"]
    mean_forecast_confidence: Confidence
    mean_bust_probability: Probability
    predicted_bust_cell_percentage: Confidence
    mean_expected_absolute_error_mm: Annotated[float, Field(ge=0)]
    mean_gefs_end_window_spread_6h_mm: Annotated[float, Field(ge=0)]
    highest_risk_cell: V2GridCell
    hotspot_count: int

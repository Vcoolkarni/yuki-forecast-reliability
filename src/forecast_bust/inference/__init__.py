"""Operational inference API; no acquisition, reference data, or fitting."""

from .service import ForecastInference, load_inference_config

__all__ = ["ForecastInference", "load_inference_config"]

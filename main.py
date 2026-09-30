"""Vercel ASGI entrypoint for the existing Yuki FastAPI application."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from forecast_bust.api.app import app  # noqa: E402

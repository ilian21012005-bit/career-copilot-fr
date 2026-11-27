"""Career Copilot standalone HTTP API (FastAPI + Pydantic v2 + Jinja2)."""

from __future__ import annotations

from .app import FASTAPI_AVAILABLE, create_app, run_server
from .auth import MIN_TOKEN_LENGTH, TokenSettings, load_api_token, verify_auth_header
from .service import CareerApiService

__all__ = [
    "FASTAPI_AVAILABLE",
    "MIN_TOKEN_LENGTH",
    "CareerApiService",
    "TokenSettings",
    "create_app",
    "load_api_token",
    "run_server",
    "verify_auth_header",
]

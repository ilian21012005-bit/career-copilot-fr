"""FastAPI application factory and Uvicorn runner for standalone Career Copilot."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from career_copilot import __version__
from career_copilot.api.auth import build_auth_dependency, load_api_token
from career_copilot.api.routes_applications import (
    register_application_and_ops_routes,
    register_setup_and_web_routes,
)
from career_copilot.api.routes_offers import register_core_and_offer_routes
from career_copilot.api.service import CareerApiService

FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
_WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


def _default_data_dir() -> Path:
    env_dir = os.getenv("CAREER_COPILOT_DATA_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return Path(__file__).resolve().parents[3] / "bot" / "data"


def register_routes(
    app: Any,
    service: CareerApiService,
    *,
    require_auth: Any,
    depends_fn: Any,
    http_exception_cls: type[Exception],
    html_response_cls: Any | None = None,
    response_cls: Any | None = None,
    json_response_cls: Any | None = None,
) -> None:
    """Bind all typed OpenAPI career routes onto a FastAPI-compatible app."""
    auth_dep = [depends_fn(require_auth)]
    register_core_and_offer_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
        response_cls=response_cls,
        json_response_cls=json_response_cls,
    )
    register_application_and_ops_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
        json_response_cls=json_response_cls,
    )
    register_setup_and_web_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
        web_root=_WEB_ROOT,
        html_response_cls=html_response_cls,
    )


def create_app(
    *,
    data_dir: Path | str | None = None,
    profile_path: Path | str | None = None,
    token: str | None = None,
    token_file: Path | str | None = None,
) -> Any:
    """Build a standalone FastAPI app (requires `uv sync` with fastapi + jinja2)."""
    try:
        from fastapi import Depends, FastAPI, Header, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        raise RuntimeError(
            "FastAPI n'est pas installé dans cet environnement Python. "
            "Exécutez `uv sync` depuis le dossier Job-Etudiant/."
        ) from exc

    resolved_data_dir = Path(data_dir) if data_dir is not None else _default_data_dir()
    resolved_token_file = (
        Path(token_file) if token_file is not None else resolved_data_dir / "career-copilot-token"
    )
    token_settings = load_api_token(
        explicit_token=token,
        token_file=resolved_token_file,
    )
    service = CareerApiService(
        data_dir=resolved_data_dir,
        profile_path=profile_path,
    )
    app = FastAPI(
        title="Career Copilot FR API",
        version=__version__,
        description=(
            "API locale zero-PII de gestion des offres, dossiers, candidatures, "
            "relances, analytique, cycles bornés, préparation d'entretien et profil."
        ),
    )

    @app.exception_handler(HTTPException)
    def _http_exception_handler(_request: Any, exc: Any) -> Any:
        code = str(getattr(exc, "code", "") or f"http_{exc.status_code}")
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail, "code": code},
            headers=getattr(exc, "headers", None),
        )

    require_auth = build_auth_dependency(
        token_settings.token,
        http_exception_cls=HTTPException,
        header_fn=Header,
    )
    register_routes(
        app,
        service,
        require_auth=require_auth,
        depends_fn=Depends,
        http_exception_cls=HTTPException,
        html_response_cls=HTMLResponse,
        response_cls=Response,
        json_response_cls=JSONResponse,
    )
    static_dir = _WEB_ROOT / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.state.career_service = service
    return app


def run_server() -> None:
    """Console entrypoint `career-copilot-api` (binds 127.0.0.1:8765 by default)."""
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "Uvicorn n'est pas installé dans cet environnement. "
            "Exécutez `uv sync` depuis Job-Etudiant/."
        ) from exc

    host = os.getenv("CAREER_COPILOT_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("CAREER_COPILOT_PORT", "8765"))
    app = create_app()
    uvicorn.run(app, host=host, port=port)

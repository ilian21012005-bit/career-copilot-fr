"""Application, followup, analytics, run, interview-prep, setup, and web routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from career_copilot.api.routes_offers import raise_http_error
from career_copilot.api.runs_service import ApiServiceError
from career_copilot.api.schemas import (
    AnalyticsResponse,
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationSummary,
    DailyRunTriggerRequest,
    DailyRunTriggerResponse,
    FollowupListResponse,
    InterviewPrepBrief,
    ManualApplicationRequest,
    ManualApplicationResponse,
    ManualWithdrawalResponse,
    RunDetailResponse,
    RunListResponse,
    SetupProfileUpdateRequest,
    SetupStatusResponse,
    SyncRunTriggerRequest,
    SyncRunTriggerResponse,
)
from career_copilot.api.service import CareerApiService


def _register_application_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: type[Exception],
    json_response_cls: Any | None = None,
) -> None:
    @app.get(
        "/api/v1/applications",
        response_model=ApplicationListResponse,
        dependencies=auth_dep,
        tags=["applications"],
    )
    def list_applications(
        include_legacy: bool = True,
        status: str | None = None,
        limit: int = 50,
        since_days: int | None = None,
    ) -> ApplicationListResponse:
        return service.list_applications(
            include_legacy=include_legacy,
            status=status,
            limit=limit,
            since_days=since_days,
        )

    @app.post(
        "/api/v1/applications",
        response_model=ApplicationSummary,
        status_code=201,
        dependencies=auth_dep,
        tags=["applications"],
    )
    def create_application(payload: ApplicationCreateRequest) -> ApplicationSummary:
        try:
            return service.create_application(payload)
        except LookupError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=404,
                detail=str(exc),
                code="offer_not_found",
            ) from exc
        except ValueError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=400,
                detail=str(exc),
                code="invalid_application",
            ) from exc

    @app.post(
        "/api/v1/applications/manual",
        response_model=ManualApplicationResponse,
        status_code=201,
        dependencies=auth_dep,
        tags=["applications"],
    )
    def declare_manual_application(payload: ManualApplicationRequest) -> Any:
        try:
            changed, result = service.declare_manual_application(payload)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc
        if json_response_cls is not None:
            return json_response_cls(
                status_code=201 if changed else 200, content=result.model_dump()
            )
        return result

    @app.delete(
        "/api/v1/applications/manual/{offer_id}",
        response_model=ManualWithdrawalResponse,
        dependencies=auth_dep,
        tags=["applications"],
    )
    def withdraw_manual_application(
        offer_id: str, url: str | None = None
    ) -> ManualWithdrawalResponse:
        try:
            return service.withdraw_manual_application(offer_id, url=url)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc


def _register_ops_and_run_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: type[Exception],
) -> None:
    @app.get(
        "/api/v1/followups",
        response_model=FollowupListResponse,
        dependencies=auth_dep,
        tags=["followups"],
    )
    def list_followups(due_only: bool = False) -> FollowupListResponse:
        return service.list_followups(due_only=due_only)

    @app.get(
        "/api/v1/analytics",
        response_model=AnalyticsResponse,
        dependencies=auth_dep,
        tags=["analytics"],
    )
    def get_analytics() -> AnalyticsResponse:
        return service.analytics()

    @app.get(
        "/api/v1/runs",
        response_model=RunListResponse,
        dependencies=auth_dep,
        tags=["runs"],
    )
    def list_runs(limit: int = 8) -> RunListResponse:
        return service.list_runs(limit=limit)

    @app.post(
        "/api/v1/runs/daily",
        response_model=DailyRunTriggerResponse,
        status_code=202,
        dependencies=auth_dep,
        tags=["runs"],
    )
    def trigger_daily_run(
        payload: DailyRunTriggerRequest | None = None,
    ) -> DailyRunTriggerResponse:
        req = payload if payload is not None else DailyRunTriggerRequest()
        try:
            return service.trigger_daily_run(req)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc

    @app.post(
        "/api/v1/runs/sync",
        response_model=SyncRunTriggerResponse,
        dependencies=auth_dep,
        tags=["runs"],
    )
    def trigger_sync_run(
        payload: SyncRunTriggerRequest | None = None,
    ) -> SyncRunTriggerResponse:
        req = payload if payload is not None else SyncRunTriggerRequest()
        try:
            return service.trigger_sync_run(req)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc

    @app.get(
        "/api/v1/runs/{run_id}",
        response_model=RunDetailResponse,
        dependencies=auth_dep,
        tags=["runs"],
    )
    def get_run(run_id: int) -> RunDetailResponse:
        try:
            return service.get_run(run_id)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc

    @app.get(
        "/api/v1/interview-prep/{offer_id}",
        response_model=InterviewPrepBrief,
        dependencies=auth_dep,
        tags=["interview-prep"],
    )
    def get_interview_prep(offer_id: str) -> InterviewPrepBrief:
        brief = service.get_interview_prep(offer_id)
        if brief is None:
            raise raise_http_error(
                http_exception_cls,
                status_code=404,
                detail="Offre introuvable",
                code="offer_not_found",
            )
        return brief


def register_application_and_ops_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: type[Exception],
    json_response_cls: Any | None = None,
) -> None:
    """Bind applications, manual declarations, followups, analytics, runs, and interview prep."""
    _register_application_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
        json_response_cls=json_response_cls,
    )
    _register_ops_and_run_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
    )


def register_setup_and_web_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: type[Exception],
    web_root: Path,
    html_response_cls: Any | None = None,
) -> None:
    """Bind profile setup routes and optional standalone web UI entrypoint."""

    @app.get(
        "/api/v1/setup",
        response_model=SetupStatusResponse,
        dependencies=auth_dep,
        tags=["setup"],
    )
    def get_setup() -> SetupStatusResponse:
        return service.get_setup()

    @app.put(
        "/api/v1/setup",
        response_model=SetupStatusResponse,
        dependencies=auth_dep,
        tags=["setup"],
    )
    def update_setup(payload: SetupProfileUpdateRequest) -> SetupStatusResponse:
        try:
            return service.update_setup(payload)
        except ValueError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=400,
                detail=str(exc),
                code="invalid_profile",
            ) from exc

    if html_response_cls is not None:
        index_file = web_root / "templates" / "index.html"

        @app.get("/", response_class=html_response_cls, include_in_schema=False)
        def index_page() -> str:
            if index_file.is_file():
                return index_file.read_text(encoding="utf-8")
            return "<!doctype html><html><body><h1>Career Copilot</h1></body></html>"

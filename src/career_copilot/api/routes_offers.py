"""Health, status, quality, offer, letter, and kit routes for Career Copilot API."""

from __future__ import annotations

from typing import Any

from career_copilot.api.runs_service import ApiServiceError
from career_copilot.api.schemas import (
    HealthResponse,
    KitListResponse,
    OfferDetail,
    OfferLetterResponse,
    OfferListResponse,
    OfferStatusUpdate,
    QualitySummaryResponse,
    StatusResponse,
)
from career_copilot.api.service import CareerApiService


def raise_http_error(
    http_exception_cls: Any,
    *,
    status_code: int,
    detail: str,
    code: str,
) -> Exception:
    exc: Any = http_exception_cls(status_code=status_code, detail=detail)
    exc.code = code
    return exc


def _register_health_and_status_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: Any,
    json_response_cls: Any | None = None,
) -> None:
    @app.get("/healthz", response_model=HealthResponse, tags=["health"])
    def healthz() -> Any:
        result = service.healthz()
        if result.status == "error":
            if json_response_cls is not None:
                return json_response_cls(status_code=503, content=result.model_dump())
            raise raise_http_error(
                http_exception_cls,
                status_code=503,
                detail="Base SQLite indisponible",
                code="service_unhealthy",
            )
        return result

    @app.get(
        "/api/v1/status",
        response_model=StatusResponse,
        dependencies=auth_dep,
        tags=["career"],
    )
    def get_status() -> StatusResponse:
        return service.status()

    @app.get(
        "/api/v1/quality/summary",
        response_model=QualitySummaryResponse,
        dependencies=auth_dep,
        tags=["quality"],
    )
    def get_quality_summary() -> QualitySummaryResponse:
        return service.quality_summary()


def _register_offer_and_kit_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: type[Exception],
    response_cls: Any | None = None,
) -> None:
    @app.get(
        "/api/v1/offers",
        response_model=OfferListResponse,
        dependencies=auth_dep,
        tags=["offers"],
    )
    def list_offers(
        track: str | None = None,
        status: str | None = None,
        q: str | None = None,
        company: str | None = None,
        exact_company: bool | None = None,
        min_score: int | None = None,
        zone: str | None = None,
        eligible: bool = False,
        limit: int = 50,
    ) -> OfferListResponse:
        return service.list_offers(
            track=track,
            status=status,
            q=q,
            company=company,
            exact_company=exact_company,
            min_score=min_score,
            zone=zone,
            eligible=eligible,
            limit=limit,
        )

    @app.get(
        "/api/v1/offers/{offer_id}",
        response_model=OfferDetail,
        dependencies=auth_dep,
        tags=["offers"],
    )
    def get_offer(offer_id: str) -> OfferDetail:
        offer = service.get_offer(offer_id)
        if offer is None:
            raise raise_http_error(
                http_exception_cls,
                status_code=404,
                detail="Offre introuvable",
                code="offer_not_found",
            )
        return offer

    @app.patch(
        "/api/v1/offers/{offer_id}/status",
        response_model=OfferDetail,
        dependencies=auth_dep,
        tags=["offers"],
    )
    def update_offer_status(offer_id: str, payload: OfferStatusUpdate) -> OfferDetail:
        updated = service.update_offer_status(offer_id, payload)
        if updated is None:
            raise raise_http_error(
                http_exception_cls,
                status_code=404,
                detail="Offre introuvable",
                code="offer_not_found",
            )
        return updated

    @app.get(
        "/api/v1/offers/{offer_id}/letter",
        response_model=OfferLetterResponse,
        dependencies=auth_dep,
        tags=["offers"],
    )
    def get_offer_letter(offer_id: str) -> OfferLetterResponse:
        try:
            return service.get_offer_letter(offer_id)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc

    @app.get(
        "/api/v1/offers/{offer_id}/letter.pdf",
        dependencies=auth_dep,
        tags=["offers"],
    )
    def get_offer_letter_pdf(offer_id: str) -> Any:
        try:
            pdf_bytes, filename = service.get_offer_letter_pdf(offer_id)
        except ApiServiceError as exc:
            raise raise_http_error(
                http_exception_cls,
                status_code=exc.status_code,
                detail=exc.detail,
                code=exc.code,
            ) from exc
        headers = {"Content-Disposition": f'inline; filename="{filename}"'}
        if response_cls is not None:
            return response_cls(content=pdf_bytes, media_type="application/pdf", headers=headers)
        return {"content": pdf_bytes, "media_type": "application/pdf", "headers": headers}

    @app.get(
        "/api/v1/kits",
        response_model=KitListResponse,
        dependencies=auth_dep,
        tags=["kits"],
    )
    def list_kits(ready_only: bool = False, limit: int = 100) -> KitListResponse:
        return service.list_kits(ready_only=ready_only, limit=limit)


def register_core_and_offer_routes(
    app: Any,
    service: CareerApiService,
    *,
    auth_dep: list[Any],
    http_exception_cls: type[Exception],
    response_cls: Any | None = None,
    json_response_cls: Any | None = None,
) -> None:
    """Bind health, status, quality, offer, letter, and kit endpoints."""
    _register_health_and_status_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
        json_response_cls=json_response_cls,
    )
    _register_offer_and_kit_routes(
        app,
        service,
        auth_dep=auth_dep,
        http_exception_cls=http_exception_cls,
        response_cls=response_cls,
    )

"""Application listing, creation, and manual declaration/withdrawal helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from career_copilot.api.offers_service import list_kits, row_value
from career_copilot.api.runs_service import ApiServiceError
from career_copilot.api.schemas import (
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationSummary,
    ManualApplicationRequest,
    ManualApplicationResponse,
    ManualWithdrawalResponse,
)
from career_copilot.store import (
    MANUAL_APPLICATION_CHANNELS,
    DatabaseHandle,
    now_iso,
)
from career_copilot.store import applications as apps_store
from career_copilot.store import offers as offers_store
from career_copilot.store import submissions as submissions_store


def application_row_to_summary(row: Any, *, url: str = "") -> ApplicationSummary:
    channel = str(row["channel"] or "")
    proof_kind = str(row["proof_kind"] or "")
    proof_ref = str(row["proof_reference"] or "")
    return ApplicationSummary(
        id=int(row["id"]) if row["id"] is not None else None,
        offer_id=str(row["offer_id"] or ""),
        company=str(row["company"] or ""),
        title=str(row["title"] or ""),
        applied_at=str(row["applied_at"] or ""),
        channel=channel,
        url=url or str(row_value(row, "url", "") or ""),
        evidence=str(row["evidence"] or ""),
        proof_kind=proof_kind,
        proof_reference=proof_ref,
        has_proof=bool(proof_kind and proof_ref),
        manual=channel in MANUAL_APPLICATION_CHANNELS,
        status=str(row["status"] or "sent"),
    )


def _latest_application_for(
    handle: DatabaseHandle, offer_id: str, offer_row: Any
) -> ApplicationSummary | None:
    with handle.db() as conn:
        top = conn.execute(
            "SELECT * FROM applications WHERE offer_id = ? AND status != 'withdrawn' "
            "ORDER BY id DESC LIMIT 1",
            (offer_id,),
        ).fetchone()
    if top is None:
        return None
    return application_row_to_summary(top, url=str(offer_row["url"] or ""))


def list_applications(
    handle: DatabaseHandle,
    *,
    include_legacy: bool = True,
    status: str | None = None,
    limit: int = 50,
    since_days: int | None = None,
) -> ApplicationListResponse:
    bounded = max(1, min(int(limit), 200))
    query = (
        "SELECT a.*, COALESCE(o.url, '') AS url FROM applications a "
        "LEFT JOIN offers o ON o.id = a.offer_id WHERE a.status != 'withdrawn'"
    )
    params: list[Any] = []
    if status:
        query += " AND a.status = ?"
        params.append(status)
    if not include_legacy:
        query += " AND COALESCE(a.offer_id, '') != ''"
    if since_days is not None:
        bounded_days = max(1, min(int(since_days), 365))
        cutoff = (datetime.now().astimezone() - timedelta(days=bounded_days)).isoformat(
            timespec="seconds"
        )
        query += " AND a.applied_at >= ?"
        params.append(cutoff)
    query += " ORDER BY a.applied_at DESC LIMIT ?"
    params.append(bounded)
    with handle.db() as conn:
        rows = list(conn.execute(query, params))
    items = [application_row_to_summary(row) for row in rows]
    kits = list_kits(handle, limit=bounded).items
    return ApplicationListResponse(
        total=len(items),
        applied_today=apps_store.applied_today(handle),
        items=items,
        kits=kits,
    )


def create_application(
    handle: DatabaseHandle, payload: ApplicationCreateRequest
) -> ApplicationSummary:
    row = offers_store.get(handle, payload.offer_id)
    if row is None:
        raise LookupError(f"Offre introuvable : {payload.offer_id}")
    recorded = apps_store.confirm(
        handle,
        payload.offer_id,
        channel=payload.channel,
        note=payload.note,
        proof_kind=payload.proof_kind,
        proof_reference=payload.proof_reference,
    )
    if not recorded and not apps_store.has_application(handle, payload.offer_id):
        raise ValueError("Impossible d'enregistrer la candidature pour cette offre.")
    latest = _latest_application_for(handle, payload.offer_id, row)
    if latest is not None:
        return latest
    return ApplicationSummary(
        offer_id=payload.offer_id,
        company=str(row["company"] or ""),
        title=str(row["title"] or ""),
        applied_at=now_iso(),
        channel=payload.channel,
        url=str(row["url"] or ""),
        evidence=payload.note,
        proof_kind=payload.proof_kind,
        proof_reference=payload.proof_reference,
        has_proof=bool(payload.proof_kind and payload.proof_reference),
        manual=payload.channel in MANUAL_APPLICATION_CHANNELS,
    )


def declare_manual_application(
    handle: DatabaseHandle, payload: ManualApplicationRequest
) -> tuple[bool, ManualApplicationResponse]:
    if not payload.offer_id and not payload.url:
        raise ApiServiceError(400, "offer_id ou url requis", code="invalid_request")
    row = offers_store.get(handle, payload.offer_id) if payload.offer_id else None
    if row is None and payload.url:
        row = offers_store.by_url(handle, payload.url.strip())
    if row is None:
        raise ApiServiceError(404, "Offre introuvable", code="offer_not_found")
    offer_id = str(row["id"])
    channel = (
        payload.channel if payload.channel in MANUAL_APPLICATION_CHANNELS else "telegram-manuel"
    )
    existing = _latest_application_for(handle, offer_id, row)
    if existing is not None:
        return False, ManualApplicationResponse(
            changed=False,
            reason="already_recorded",
            application=existing,
        )
    recorded = submissions_store.declare_manual_application(
        handle,
        offer_id,
        channel=channel,
        note=payload.note,
        allow_existing=False,
    )
    latest = _latest_application_for(handle, offer_id, row)
    if not recorded or latest is None:
        raise ApiServiceError(
            409,
            "Candidature déjà enregistrée ou verrouillée",
            code="application_conflict",
        )
    return True, ManualApplicationResponse(changed=True, application=latest)


def withdraw_manual_application(
    handle: DatabaseHandle, offer_id: str, *, url: str | None = None
) -> ManualWithdrawalResponse:
    row = offers_store.get(handle, offer_id)
    if row is None and url:
        row = offers_store.by_url(handle, url.strip())
    if row is None:
        raise ApiServiceError(404, "Offre introuvable", code="offer_not_found")
    resolved_id = str(row["id"])
    withdrawn = submissions_store.withdraw_manual_application(handle, resolved_id)
    if not withdrawn:
        raise ApiServiceError(
            409,
            "Seule une déclaration manuelle peut être annulée",
            code="not_manual_application",
        )
    updated = offers_store.get(handle, resolved_id) or row
    return ManualWithdrawalResponse(
        changed=True,
        offer_id=resolved_id,
        company=str(updated["company"] or ""),
        title=str(updated["title"] or ""),
        status=str(updated["status"] or "new"),
    )

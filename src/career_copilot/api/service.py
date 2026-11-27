"""Pure standalone career domain service backing the FastAPI routes."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from career_copilot import __version__
from career_copilot.api.analytics_service import (
    build_analytics,
    build_followups,
    build_quality_summary,
    read_last_run_state,
)
from career_copilot.api.applications_service import (
    create_application,
    declare_manual_application,
    list_applications,
    withdraw_manual_application,
)
from career_copilot.api.offers_service import (
    decode_json_list,
    get_offer_letter,
    get_offer_letter_pdf,
    list_kits,
    list_offers,
    row_to_offer_detail,
)
from career_copilot.api.runs_service import (
    ApiServiceError,
    get_run,
    list_runs,
    trigger_daily_run,
    trigger_sync_run,
)
from career_copilot.api.schemas import (
    AnalyticsResponse,
    ApplicationCreateRequest,
    ApplicationListResponse,
    ApplicationSummary,
    DailyRunTriggerRequest,
    DailyRunTriggerResponse,
    FollowupListResponse,
    HealthCheckDetail,
    HealthMigrationsCheck,
    HealthResponse,
    HealthWalCheck,
    InterviewPrepBrief,
    KitListResponse,
    ManualApplicationRequest,
    ManualApplicationResponse,
    ManualWithdrawalResponse,
    OfferDetail,
    OfferLetterResponse,
    OfferListResponse,
    OfferStatusUpdate,
    QualitySummaryResponse,
    RunDetailResponse,
    RunListResponse,
    SetupProfileUpdateRequest,
    SetupStatusResponse,
    StatusCounts,
    StatusLastSummary,
    StatusResponse,
    SyncRunTriggerRequest,
    SyncRunTriggerResponse,
)
from career_copilot.db.migrations import current_version
from career_copilot.profile import (
    CandidateProfileConfig,
    load_profile,
    save_profile_payload,
)
from career_copilot.store import DatabaseHandle, now_iso
from career_copilot.store import applications as apps_store
from career_copilot.store import kits as kits_store
from career_copilot.store import offers as offers_store
from career_copilot.store import plan as plan_store
from career_copilot.store import submissions as submissions_store


class CareerApiService:
    """Explicitly injected career domain service (no global module coupling)."""

    def __init__(
        self,
        *,
        data_dir: Path | str,
        profile_path: Path | str | None = None,
        db_name: str = "hellowork.db",
        daily_runner: Callable[[int, bool], dict[str, Any] | None] | None = None,
        sync_runner: Callable[[str], int] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / db_name
        self.profile_file = (
            Path(profile_path)
            if profile_path is not None
            else self.data_dir / "candidate-profile.json"
        )
        self.handle = DatabaseHandle.for_path(self.db_path, data_dir=self.data_dir)
        self._daily_runner = daily_runner
        self._sync_runner = sync_runner
        self._started_monotonic = time.monotonic()
        self.handle.init()

    def _profile(self) -> CandidateProfileConfig:
        return load_profile(self.profile_file)

    def _schema_info(self) -> tuple[bool, int]:
        with self.handle.db() as conn:
            mode_row = conn.execute("PRAGMA journal_mode").fetchone()
            journal_mode = str(mode_row[0]).lower() if mode_row else ""
            schema_ver = current_version(conn)
        return journal_mode == "wal", schema_ver

    def healthz(self) -> HealthResponse:
        uptime = round(max(0.0, time.monotonic() - self._started_monotonic), 3)
        try:
            wal_ok, schema_ver = self._schema_info()
        except (sqlite3.Error, OSError, ValueError):
            return HealthResponse(
                status="error",
                version=__version__,
                uptime_s=uptime,
                checked_at=now_iso(),
                checks=HealthCheckDetail(
                    sqlite_wal=HealthWalCheck(status="error"),
                    migrations=HealthMigrationsCheck(status="error", user_version=0),
                    profile_configured=False,
                ),
            )
        cfg = self._profile()
        healthy = wal_ok and schema_ver > 0
        return HealthResponse(
            status="ok" if healthy else "degraded",
            version=__version__,
            uptime_s=uptime,
            checked_at=now_iso(),
            checks=HealthCheckDetail(
                sqlite_wal=HealthWalCheck(status="ok" if wal_ok else "degraded"),
                migrations=HealthMigrationsCheck(
                    status="ok" if schema_ver > 0 else "degraded",
                    user_version=schema_ver,
                ),
                profile_configured=cfg.configured,
            ),
        )

    def status(self) -> StatusResponse:
        _, schema_ver = self._schema_info()
        cfg = self._profile()
        summary = apps_store.stats(self.handle)
        by_status = offers_store.counts(self.handle)
        offers_active = sum(
            by_status.get(st, 0) for st in ("new", "shortlist", "prepared", "to_finish")
        )
        last_state = read_last_run_state(self.data_dir)
        raw_last = last_state.get("last_summary")
        last_summary = (
            StatusLastSummary(
                lm_generated=max(0, int(raw_last.get("lm_generated") or 0)),
                lm_failed=max(0, int(raw_last.get("lm_failed") or 0)),
                errors=[str(err) for err in (raw_last.get("errors") or [])],
            )
            if isinstance(raw_last, dict)
            else StatusLastSummary()
        )
        return StatusResponse(
            version=__version__,
            schema_version=schema_ver,
            profile_configured=cfg.configured,
            preset_id=cfg.preset_id,
            contracts=list(cfg.contracts),
            db_ok=True,
            offers_active=offers_active,
            applications_total=summary["candidatures"],
            last_run_at=str(last_state["last_run_at"]) if last_state.get("last_run_at") else None,
            last_auto_success_at=(
                str(last_state["last_auto_success_at"])
                if last_state.get("last_auto_success_at")
                else None
            ),
            last_summary=last_summary,
            counts=StatusCounts(
                offers_total=summary["offres"],
                offers_by_status=by_status,
                offers_by_zone=offers_store.zone_counts(self.handle),
                kits_total=summary["dossiers"],
                applications_sent=summary["candidatures"],
                applied_today=summary["aujourd'hui"],
                planned_today=plan_store.plan_count(self.handle),
                unreconciled_submissions=submissions_store.has_unreconciled_submissions(
                    self.handle
                ),
            ),
            checked_at=now_iso(),
        )

    def quality_summary(self) -> QualitySummaryResponse:
        return build_quality_summary(self.handle, self.data_dir)

    def list_offers(
        self,
        *,
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
        return list_offers(
            self.handle,
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

    def get_offer(self, offer_id: str) -> OfferDetail | None:
        row = offers_store.get(self.handle, offer_id)
        if row is None:
            return None
        kit = kits_store.kit_for(self.handle, offer_id)
        return row_to_offer_detail(row, has_kit=kit is not None)

    def update_offer_status(self, offer_id: str, payload: OfferStatusUpdate) -> OfferDetail | None:
        updated = offers_store.set_status(self.handle, offer_id, payload.status, payload.note)
        return self.get_offer(offer_id) if updated else None

    def get_offer_letter(self, offer_id: str) -> OfferLetterResponse:
        return get_offer_letter(self.handle, self.data_dir, offer_id)

    def get_offer_letter_pdf(self, offer_id: str) -> tuple[bytes, str]:
        return get_offer_letter_pdf(self.handle, self.data_dir, offer_id)

    def list_kits(self, *, ready_only: bool = False, limit: int = 100) -> KitListResponse:
        return list_kits(self.handle, ready_only=ready_only, limit=limit)

    def list_applications(
        self,
        *,
        include_legacy: bool = True,
        status: str | None = None,
        limit: int = 50,
        since_days: int | None = None,
    ) -> ApplicationListResponse:
        return list_applications(
            self.handle,
            include_legacy=include_legacy,
            status=status,
            limit=limit,
            since_days=since_days,
        )

    def create_application(self, payload: ApplicationCreateRequest) -> ApplicationSummary:
        return create_application(self.handle, payload)

    def declare_manual_application(
        self, payload: ManualApplicationRequest
    ) -> tuple[bool, ManualApplicationResponse]:
        return declare_manual_application(self.handle, payload)

    def withdraw_manual_application(
        self, offer_id: str, *, url: str | None = None
    ) -> ManualWithdrawalResponse:
        return withdraw_manual_application(self.handle, offer_id, url=url)

    def list_followups(self, *, due_only: bool = False) -> FollowupListResponse:
        return build_followups(self.handle, due_only=due_only)

    def analytics(self) -> AnalyticsResponse:
        return build_analytics(self.handle, self.data_dir)

    def list_runs(self, *, limit: int = 8) -> RunListResponse:
        return list_runs(self.handle, limit=limit)

    def get_run(self, run_id: int) -> RunDetailResponse:
        run = get_run(self.handle, run_id)
        if run is None:
            raise ApiServiceError(404, "Cycle introuvable", code="run_not_found")
        return run

    def trigger_daily_run(self, payload: DailyRunTriggerRequest) -> DailyRunTriggerResponse:
        return trigger_daily_run(
            self.handle,
            auto_submit=payload.auto_submit,
            runner=self._daily_runner,
        )

    def trigger_sync_run(self, payload: SyncRunTriggerRequest) -> SyncRunTriggerResponse:
        return trigger_sync_run(
            self.handle,
            source=payload.source,
            runner=self._sync_runner,
        )

    def get_interview_prep(self, offer_id: str) -> InterviewPrepBrief | None:
        row = offers_store.get(self.handle, offer_id)
        if row is None:
            return None
        cfg = self._profile()
        offer_text = " ".join(
            str(row[field] or "") for field in ("title", "description", "missions", "profile")
        ).lower()
        matched_facts = [
            fact
            for fact in cfg.facts
            if any(
                token for token in fact.lower().split() if len(token) > 4 and token in offer_text
            )
        ] or list(cfg.facts[:3])
        gaps = decode_json_list(row["gaps"])
        company = str(row["company"] or "l'entreprise")
        title = str(row["title"] or "le poste")
        return InterviewPrepBrief(
            offer_id=str(row["id"]),
            company=company,
            title=title,
            contract=str(row["contract"] or ""),
            score=max(0, min(100, int(row["score"] or 0))),
            matched_facts=matched_facts[:6],
            gaps_to_address=gaps[:6],
            questions_to_prepare=[
                f"Quelles seront les priorités des 30 premiers jours sur « {title} » ?",
                f"Comment l'équipe de {company} organise-t-elle l'encadrement et les revues ?",
                "Quels outils ou environnements sont utilisés au quotidien sur ce périmètre ?",
            ],
            checklist=[
                "Relire uniquement les faits vérifiés du profil candidat (zéro invention).",
                "Préparer deux exemples STAR courts reliés aux missions annoncées.",
                "Vérifier la logistique (date, lieu/visio, interlocuteurs, disponibilité).",
            ],
        )

    def get_setup(self) -> SetupStatusResponse:
        cfg = self._profile()
        return SetupStatusResponse(
            configured=cfg.configured,
            schema_version=cfg.schema_version,
            preset=cfg.preset_id,
            contracts=list(cfg.contracts),
            zone_preset=cfg.zone_preset,
            zones=[dict(z) for z in cfg.zones],
            job_radius_km=cfg.job_radius_km,
            facts_count=len(cfg.facts),
            skills_count=len(cfg.owned_skills),
            min_score=cfg.min_score,
            daily_target=cfg.daily_target,
            daily_max=cfg.daily_max,
            load_error=cfg.load_error,
        )

    def update_setup(self, payload: SetupProfileUpdateRequest) -> SetupStatusResponse:
        raw = payload.model_dump(exclude_none=True)
        save_profile_payload(raw, path=self.profile_file)
        return self.get_setup()

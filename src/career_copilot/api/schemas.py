"""Pydantic v2 OpenAPI request and response schemas for Career Copilot."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from career_copilot.api.schemas_ops import (
    AnalyticsFreshnessItem,
    AnalyticsKpis,
    AnalyticsResponse,
    AnalyticsStatusBucket,
    DailyRunTriggerRequest,
    DailyRunTriggerResponse,
    FollowupCandidate,
    FollowupListResponse,
    QualityIssue,
    QualityMetrics,
    QualitySummaryResponse,
    RunDetailResponse,
    RunListResponse,
    RunSummary,
    SyncRunTriggerRequest,
    SyncRunTriggerResponse,
)


class HealthWalCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "error"]


class HealthMigrationsCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "error"]
    user_version: int = Field(ge=0)


class HealthCheckDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sqlite_wal: HealthWalCheck
    migrations: HealthMigrationsCheck
    profile_configured: bool = False


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = "career-copilot-fr"
    version: str
    status: Literal["ok", "degraded", "error"]
    checks: HealthCheckDetail
    uptime_s: float = Field(ge=0.0)
    checked_at: str


class StatusLastSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    lm_generated: int = Field(default=0, ge=0)
    lm_failed: int = Field(default=0, ge=0)
    errors: list[str] = Field(default_factory=list)


class StatusCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offers_total: int = Field(ge=0)
    offers_by_status: dict[str, int] = Field(default_factory=dict)
    offers_by_zone: dict[str, int] = Field(default_factory=dict)
    kits_total: int = Field(ge=0)
    applications_sent: int = Field(ge=0)
    applied_today: int = Field(ge=0)
    planned_today: int = Field(ge=0)
    unreconciled_submissions: bool = False


class StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = "career-copilot-fr"
    version: str
    schema_version: int = Field(ge=0)
    profile_configured: bool
    preset_id: str
    contracts: list[str]
    db_ok: bool = True
    offers_active: int = Field(default=0, ge=0)
    applications_total: int = Field(default=0, ge=0)
    last_run_at: str | None = None
    last_auto_success_at: str | None = None
    last_summary: StatusLastSummary = Field(default_factory=StatusLastSummary)
    counts: StatusCounts
    checked_at: str


class OfferSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    url: str = ""
    title: str = ""
    company: str = ""
    city: str = ""
    department: str = ""
    contract: str = ""
    salary: str = ""
    score: int = Field(default=0, ge=0, le=100)
    status: str = "new"
    zone: str = ""
    distance_km: float | None = None
    location_status: str = "unknown"
    is_stage: bool = False
    is_alternance: bool = False
    apply_capability: str = ""
    contact_email: str | None = None
    partner_url: str | None = None
    apply_url: str | None = None
    ats_url: str | None = None
    first_seen: str = ""
    last_seen: str = ""
    notes: str = ""
    has_kit: bool = False
    reasons: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class OfferDetail(OfferSummary):
    model_config = ConfigDict(extra="forbid")

    posted_at: str = ""
    description: str = ""
    missions: str = ""
    profile: str = ""
    benefits: str = ""
    apply_mode: str = ""


class OfferListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    items: list[OfferSummary]


class OfferLetterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str
    letter: str
    updated_at: str | None = None


class OfferStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "new",
        "shortlist",
        "prepared",
        "applied",
        "to_finish",
        "replied",
        "interview",
        "submission_unknown",
        "submission_pending",
        "ignored",
    ]
    note: str = Field(default="", max_length=500)


class KitSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str
    company: str = ""
    title: str = ""
    subject: str = ""
    created_at: str = ""
    updated_at: str = ""
    has_cv: bool = False
    has_letter: bool = False
    has_dossier: bool = False
    is_current: bool = False


class KitListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    items: list[KitSummary]


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    offer_id: str = ""
    company: str = ""
    title: str = ""
    applied_at: str
    channel: str
    url: str = ""
    evidence: str = ""
    proof_kind: str = ""
    proof_reference: str = ""
    has_proof: bool = False
    manual: bool = False
    status: str = "sent"


class ApplicationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(min_length=1, max_length=160)
    channel: str = Field(default="candidature-manuelle", min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)
    proof_kind: Literal["", "authenticated_receipt", "ats_receipt", "smtp_accepted"] = ""
    proof_reference: str = Field(default="", max_length=300)


class ManualApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str | None = Field(default=None, max_length=160)
    url: str | None = Field(default=None, max_length=500)
    channel: str = Field(default="telegram-manuel", min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


class ManualApplicationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed: bool
    reason: str | None = None
    application: ApplicationSummary


class ManualWithdrawalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed: bool
    offer_id: str
    company: str = ""
    title: str = ""
    status: str


class ApplicationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    applied_today: int = Field(ge=0)
    items: list[ApplicationSummary]
    kits: list[KitSummary] = Field(default_factory=list)


class InterviewPrepBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str
    company: str
    title: str
    contract: str
    score: int = Field(ge=0, le=100)
    matched_facts: list[str]
    gaps_to_address: list[str]
    questions_to_prepare: list[str]
    checklist: list[str]


class SetupStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configured: bool
    schema_version: int
    preset: str
    contracts: list[str]
    zone_preset: str
    zones: list[dict[str, Any]]
    job_radius_km: float
    facts_count: int = Field(ge=0)
    skills_count: int = Field(ge=0)
    min_score: int = Field(ge=0, le=100)
    daily_target: int = Field(ge=1)
    daily_max: int = Field(ge=1)
    load_error: str = ""


class SetupProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    preset: str | None = None
    contracts: list[str] | None = None
    zone_preset: str | None = None
    zones: list[Any] | None = None
    job_radius_km: float | None = Field(default=None, ge=1.0, le=150.0)
    candidate: dict[str, Any] | None = None
    facts: list[str] | None = None
    form_answers: dict[str, str] | None = None
    job_form_answers: dict[str, str] | None = None
    skills: dict[str, Any] | None = None
    preferences: dict[str, Any] | None = None


__all__ = [
    "AnalyticsFreshnessItem",
    "AnalyticsKpis",
    "AnalyticsResponse",
    "AnalyticsStatusBucket",
    "ApplicationCreateRequest",
    "ApplicationListResponse",
    "ApplicationSummary",
    "DailyRunTriggerRequest",
    "DailyRunTriggerResponse",
    "FollowupCandidate",
    "FollowupListResponse",
    "HealthCheckDetail",
    "HealthMigrationsCheck",
    "HealthResponse",
    "HealthWalCheck",
    "InterviewPrepBrief",
    "KitListResponse",
    "KitSummary",
    "ManualApplicationRequest",
    "ManualApplicationResponse",
    "ManualWithdrawalResponse",
    "OfferDetail",
    "OfferLetterResponse",
    "OfferListResponse",
    "OfferStatusUpdate",
    "OfferSummary",
    "QualityIssue",
    "QualityMetrics",
    "QualitySummaryResponse",
    "RunDetailResponse",
    "RunListResponse",
    "RunSummary",
    "SetupProfileUpdateRequest",
    "SetupStatusResponse",
    "StatusCounts",
    "StatusLastSummary",
    "StatusResponse",
    "SyncRunTriggerRequest",
    "SyncRunTriggerResponse",
]

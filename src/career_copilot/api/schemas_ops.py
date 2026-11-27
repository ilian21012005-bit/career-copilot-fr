"""Pydantic v2 OpenAPI schemas for quality, followups, analytics, and runs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QualityMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offers: int = Field(ge=0)
    applications: int = Field(ge=0)
    applications_7d: int = Field(ge=0)


class QualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "application_proof",
        "duplicate_application",
        "stale_offers",
        "funnel_stall_applications",
        "hellowork_lm_failure",
        "hellowork_cycle_stale",
    ]
    severity: Literal["info", "warning", "critical"]
    detail: str
    count: int = Field(ge=0)


class QualitySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_at: str
    metrics: QualityMetrics
    issues: list[QualityIssue] = Field(default_factory=list)


class FollowupCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = ""
    company: str = ""
    title: str = ""
    applied_date: str = ""
    applied_at: str = ""
    days_since_application: int = Field(ge=0)
    is_due: bool = False
    url: str = ""


class FollowupListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count_due: int = Field(ge=0)
    candidates: list[FollowupCandidate] = Field(default_factory=list)


class AnalyticsKpis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offers_total: int = Field(ge=0)
    applications_total: int = Field(ge=0)
    reply_total: int = Field(ge=0)


class AnalyticsFreshnessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    status: Literal["fresh", "stale", "unknown"]
    age_hours: float | None = Field(default=None, ge=0.0)


class AnalyticsStatusBucket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: int = Field(ge=0)


class AnalyticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kpis: AnalyticsKpis
    freshness: list[AnalyticsFreshnessItem] = Field(default_factory=list)
    application_statuses: list[AnalyticsStatusBucket] = Field(default_factory=list)


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    kind: Literal["daily", "sync"]
    status: Literal["running", "success", "failed"]
    started_at: str
    duration_seconds: float | None = Field(default=None, ge=0.0)
    summary: str = ""


class RunListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: list[RunSummary] = Field(default_factory=list)


class DailyRunTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_submit: bool = False


class DailyRunTriggerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int = Field(ge=1)
    status: Literal["running", "success", "failed"] = "running"


class SyncRunTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(default="imap", min_length=1, max_length=40)


class SyncRunTriggerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: int = Field(ge=1)
    status: Literal["running", "success", "failed"]
    synced_messages: int = Field(default=0, ge=0)


class RunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    kind: Literal["daily", "sync"]
    status: Literal["running", "success", "failed"]
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0.0)
    summary: str = ""
    error_code: str = ""
    synced_messages: int = Field(default=0, ge=0)

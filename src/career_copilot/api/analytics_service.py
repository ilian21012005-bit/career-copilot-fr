"""Read-only quality audit, followups, and funnel analytics helpers for the API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from career_copilot.api.schemas_ops import (
    AnalyticsFreshnessItem,
    AnalyticsKpis,
    AnalyticsResponse,
    AnalyticsStatusBucket,
    FollowupCandidate,
    FollowupListResponse,
    QualityIssue,
    QualityMetrics,
    QualitySummaryResponse,
)
from career_copilot.store.connection import MANUAL_APPLICATION_CHANNELS, DatabaseHandle, now_iso


def read_last_run_state(data_dir: Path) -> dict[str, Any]:
    """Read `hellowork/last-run.json` safely if present and regular (non-symlink)."""
    path = data_dir / "hellowork" / "last-run.json"
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    now = datetime.now().astimezone()
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=now.tzinfo)


def _age_hours(raw: str | None) -> float | None:
    parsed = _parse_iso(raw)
    if parsed is None:
        return None
    delta = (datetime.now().astimezone() - parsed).total_seconds() / 3600.0
    return round(max(0.0, delta), 2)


def _query_quality_counts(handle: DatabaseHandle) -> dict[str, int]:
    now = datetime.now().astimezone()
    cutoff_7d = (now - timedelta(days=7)).isoformat(timespec="seconds")
    cutoff_30d = (now - timedelta(days=30)).isoformat(timespec="seconds")
    placeholders = ",".join("?" for _ in MANUAL_APPLICATION_CHANNELS)
    with handle.db() as conn:
        offers_count = int(conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0])
        apps_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status != 'withdrawn'"
            ).fetchone()[0]
        )
        apps_7d = int(
            conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status != 'withdrawn' AND applied_at >= ?",
                (cutoff_7d,),
            ).fetchone()[0]
        )
        missing_proof = int(
            conn.execute(
                f"SELECT COUNT(*) FROM applications WHERE status = 'sent' "  # noqa: S608
                f"AND channel NOT IN ({placeholders}) "
                f"AND (COALESCE(proof_kind, '') = '' OR COALESCE(proof_reference, '') = '')",
                tuple(sorted(MANUAL_APPLICATION_CHANNELS)),
            ).fetchone()[0]
        )
        dup_rows = int(
            conn.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT offer_id FROM applications "
                "  WHERE status != 'withdrawn' AND COALESCE(offer_id, '') != '' "
                "  GROUP BY offer_id HAVING COUNT(*) > 1"
                ")"
            ).fetchone()[0]
        )
        stale_offers = int(
            conn.execute(
                "SELECT COUNT(*) FROM offers "
                "WHERE status IN ('new', 'shortlist', 'prepared') AND last_seen < ?",
                (cutoff_30d,),
            ).fetchone()[0]
        )
    return {
        "offers": offers_count,
        "applications": apps_count,
        "applications_7d": apps_7d,
        "missing_proof": missing_proof,
        "dup_rows": dup_rows,
        "stale_offers": stale_offers,
    }


def build_quality_summary(handle: DatabaseHandle, data_dir: Path) -> QualitySummaryResponse:
    """Compute read-only quality metrics and issues for `GET /api/v1/quality/summary`."""
    counts = _query_quality_counts(handle)
    issues: list[QualityIssue] = []

    if counts["missing_proof"] > 0:
        issues.append(
            QualityIssue(
                kind="application_proof",
                severity="warning",
                detail=(
                    f"{counts['missing_proof']} candidature(s) non manuelle(s) "
                    "sans preuve enregistrée"
                ),
                count=counts["missing_proof"],
            )
        )
    if counts["dup_rows"] > 0:
        issues.append(
            QualityIssue(
                kind="duplicate_application",
                severity="critical",
                detail=f"{counts['dup_rows']} offre(s) avec plusieurs candidatures actives",
                count=counts["dup_rows"],
            )
        )
    if counts["stale_offers"] > 0:
        issues.append(
            QualityIssue(
                kind="stale_offers",
                severity="info",
                detail=(
                    f"{counts['stale_offers']} offre(s) active(s) non revue(s) "
                    "depuis plus de 30 jours"
                ),
                count=counts["stale_offers"],
            )
        )
    if counts["offers"] >= 10 and counts["applications_7d"] == 0:
        issues.append(
            QualityIssue(
                kind="funnel_stall_applications",
                severity="warning",
                detail="Aucune candidature enregistrée sur les 7 derniers jours",
                count=0,
            )
        )

    last_state = read_last_run_state(data_dir)
    last_summary = last_state.get("last_summary")
    lm_failed = int(last_summary.get("lm_failed") or 0) if isinstance(last_summary, dict) else 0
    if lm_failed > 0:
        issues.append(
            QualityIssue(
                kind="hellowork_lm_failure",
                severity="warning",
                detail=f"{lm_failed} lettre(s) IA en échec lors du dernier cycle",
                count=lm_failed,
            )
        )
    cycle_age = _age_hours(last_state.get("last_run_at"))
    if cycle_age is not None and cycle_age > 36.0:
        issues.append(
            QualityIssue(
                kind="hellowork_cycle_stale",
                severity="warning",
                detail=f"Dernier cycle quotidien âgé de {cycle_age:.1f} h",
                count=1,
            )
        )

    return QualitySummaryResponse(
        checked_at=now_iso(),
        metrics=QualityMetrics(
            offers=counts["offers"],
            applications=counts["applications"],
            applications_7d=counts["applications_7d"],
        ),
        issues=issues,
    )


def build_followups(
    handle: DatabaseHandle,
    *,
    due_only: bool = False,
    delay_days: int = 7,
) -> FollowupListResponse:
    """List applications eligible for follow-up (`GET /api/v1/followups`)."""
    today_date = datetime.now().astimezone().date()
    threshold = max(1, int(delay_days))
    with handle.db() as conn:
        rows = conn.execute(
            """
            SELECT a.offer_id, a.company, a.title, a.applied_at,
                   COALESCE(o.url, '') AS url,
                   COALESCE(o.status, 'applied') AS offer_status
              FROM applications a
              LEFT JOIN offers o ON o.id = a.offer_id
             WHERE a.status != 'withdrawn'
             ORDER BY a.applied_at ASC
            """
        ).fetchall()

    candidates: list[FollowupCandidate] = []
    count_due = 0
    for row in rows:
        if str(row["offer_status"]) in ("replied", "interview", "ignored"):
            continue
        applied_raw = str(row["applied_at"] or "")
        applied_dt = _parse_iso(applied_raw)
        days_since = max(0, (today_date - applied_dt.date()).days) if applied_dt is not None else 0
        is_due = days_since >= threshold
        if is_due:
            count_due += 1
        if due_only and not is_due:
            continue
        candidates.append(
            FollowupCandidate(
                offer_id=str(row["offer_id"] or ""),
                company=str(row["company"] or ""),
                title=str(row["title"] or ""),
                applied_date=applied_raw[:10],
                applied_at=applied_raw,
                days_since_application=days_since,
                is_due=is_due,
                url=str(row["url"] or ""),
            )
        )
    return FollowupListResponse(count_due=count_due, candidates=candidates)


def build_analytics(handle: DatabaseHandle, data_dir: Path) -> AnalyticsResponse:
    """Compute funnel KPIs and freshness without host/systemd coupling."""
    with handle.db() as conn:
        offers_total = int(conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0])
        apps_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status != 'withdrawn'"
            ).fetchone()[0]
        )
        reply_total = int(
            conn.execute(
                "SELECT COUNT(*) FROM offers WHERE status IN ('replied', 'interview')"
            ).fetchone()[0]
        )
        kits_total = int(conn.execute("SELECT COUNT(*) FROM kits").fetchone()[0])
        status_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM offers GROUP BY status ORDER BY n DESC"
        ).fetchall()

    last_state = read_last_run_state(data_dir)
    age = _age_hours(last_state.get("last_run_at"))
    fresh_status = "unknown" if age is None else ("fresh" if age <= 24.0 else "stale")
    status_labels = {
        "new": "Nouvelles",
        "shortlist": "Présélectionnées",
        "prepared": "Dossiers prêts",
        "applied": "Envoyées",
        "to_finish": "À finaliser",
        "replied": "Réponses",
        "interview": "Entretiens",
        "ignored": "Ignorées",
    }
    buckets = [AnalyticsStatusBucket(label="Dossiers prêts", value=kits_total)]
    for row in status_rows:
        key = str(row["status"] or "")
        if key == "prepared":
            continue
        buckets.append(
            AnalyticsStatusBucket(
                label=status_labels.get(key, key),
                value=int(row["n"]),
            )
        )

    return AnalyticsResponse(
        kpis=AnalyticsKpis(
            offers_total=offers_total,
            applications_total=apps_total,
            reply_total=reply_total,
        ),
        freshness=[AnalyticsFreshnessItem(label="HelloWork", status=fresh_status, age_hours=age)],
        application_statuses=buckets,
    )

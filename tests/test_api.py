"""Contract and unit tests for standalone Career Copilot API schemas, auth, service, and routes."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from career_copilot.api.app import FASTAPI_AVAILABLE, create_app, register_routes
from career_copilot.api.auth import (
    MIN_TOKEN_LENGTH,
    build_auth_dependency,
    load_api_token,
    verify_auth_header,
)
from career_copilot.api.schemas import (
    ApplicationCreateRequest,
    DailyRunTriggerRequest,
    ManualApplicationRequest,
    OfferStatusUpdate,
    SetupProfileUpdateRequest,
    SyncRunTriggerRequest,
)
from career_copilot.api.service import CareerApiService
from career_copilot.profile import build_example_profile_v2
from career_copilot.store import applications as apps_store
from career_copilot.store import kits as kits_store
from career_copilot.store import offers as offers_store


@dataclass
class _StubOffer:
    id: str = "offer-101"
    url: str = "https://example.org/jobs/101"
    title: str = "Stage Administrateur Systèmes & Réseaux"
    company: str = "Exemple Infra SAS"
    city: str = "Lyon"
    department: str = "69"
    contract: str = "Stage"
    posted_at: str = "2026-11-20"
    salary: str = ""
    description: str = "Administration Linux, supervision, réseau et documentation."
    missions: str = "Maintien en condition opérationnelle Linux et réseau."
    profile: str = "Bac+3 autonome, rigoureux."
    benefits: str = ""
    apply_mode: str = "direct"
    latitude: float = 45.764
    longitude: float = 4.8357
    zone: str = "Lyon"
    distance_km: float = 5.0
    location_status: str = "in_zone"


@dataclass
class _StubScore:
    value: int = 86
    parts: dict[str, int] = None  # type: ignore[assignment]
    reasons: list[str] = None  # type: ignore[assignment]
    gaps: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parts = self.parts or {
            "contrat": 25,
            "lieu": 15,
            "compétences": 32,
            "niveau": 8,
            "fraîcheur": 6,
        }
        self.reasons = self.reasons or ["Stage ciblé", "Bassin Lyon"]
        self.gaps = self.gaps or ["Kubernetes"]


class _StubHTTPException(Exception):
    def __init__(
        self, status_code: int, detail: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}


class _StubJsonResponse:
    def __init__(self, *, status_code: int, content: Any) -> None:
        self.status_code = status_code
        self.content = content


class _StubBinaryResponse:
    def __init__(self, *, content: bytes, media_type: str, headers: dict[str, str]) -> None:
        self.content = content
        self.media_type = media_type
        self.headers = headers


class _StubApp:
    """Minimal FastAPI-compatible registrar to verify routes & metadata without fastapi."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {}
        self.route_meta: dict[tuple[str, str], dict[str, Any]] = {}

    def _register(self, method: str, path: str, kwargs: dict[str, Any]):
        def decorator(fn: Any) -> Any:
            self.routes[(method, path)] = fn
            self.route_meta[(method, path)] = kwargs
            return fn

        return decorator

    def get(self, path: str, **kwargs: Any):
        return self._register("GET", path, kwargs)

    def post(self, path: str, **kwargs: Any):
        return self._register("POST", path, kwargs)

    def put(self, path: str, **kwargs: Any):
        return self._register("PUT", path, kwargs)

    def patch(self, path: str, **kwargs: Any):
        return self._register("PATCH", path, kwargs)

    def delete(self, path: str, **kwargs: Any):
        return self._register("DELETE", path, kwargs)


class CareerApiAuthTest(unittest.TestCase):
    def test_token_generation_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "secrets" / "api.token"
            resolved = load_api_token(token_file=token_path)
            self.assertGreaterEqual(len(resolved.token), MIN_TOKEN_LENGTH)
            self.assertTrue(verify_auth_header(f"Bearer {resolved.token}", resolved.token))

            basic = base64.b64encode(f"admin:{resolved.token}".encode()).decode("ascii")
            self.assertTrue(verify_auth_header(f"Basic {basic}", resolved.token))
            self.assertFalse(verify_auth_header("Bearer wrong-token", resolved.token))
            self.assertFalse(verify_auth_header(None, resolved.token))

            dep = build_auth_dependency(resolved.token, http_exception_cls=_StubHTTPException)
            self.assertEqual(dep(f"Bearer {resolved.token}"), "authenticated")
            with self.assertRaises(_StubHTTPException) as ctx:
                dep("Bearer invalid")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertEqual(getattr(ctx.exception, "code", ""), "unauthorized")

    def test_short_explicit_token_rejected(self) -> None:
        too_short = "short-" + "val"
        with self.assertRaises(RuntimeError):
            load_api_token(explicit_token=too_short)


class CareerApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "data"
        self.service = CareerApiService(
            data_dir=self.data_dir,
            sync_runner=lambda source: 3 if source == "imap" else 0,
        )
        offers_store.save_offer(self.service.handle, _StubOffer(), _StubScore())
        offers_store.save_offer(
            self.service.handle,
            _StubOffer(
                id="offer-alt",
                url="https://example.org/jobs/alt",
                title="Alternance DevSecOps",
                company="CloudNord",
                city="Lille",
                contract="Alternance",
            ),
            _StubScore(value=78),
        )
        offers_store.save_offer(
            self.service.handle,
            _StubOffer(
                id="offer-job",
                url="https://example.org/jobs/student",
                title="Equipier Polyvalent Week-end",
                company="Librairie du Parc",
                city="Lyon",
                contract="job_etudiant",
            ),
            _StubScore(value=72),
        )
        with self.service.handle.db() as conn:
            conn.execute(
                "UPDATE offers SET partner_url = ?, apply_capability = 'manual_partner', "
                "notes = 'ATS https://ats.example.org/apply/101' WHERE id = 'offer-101'",
                ("https://ats.example.org/apply/101",),
            )
        self.stub = _StubApp()
        dep = build_auth_dependency("A" * 40, http_exception_cls=_StubHTTPException)
        register_routes(
            self.stub,
            self.service,
            require_auth=dep,
            depends_fn=lambda fn: fn,
            http_exception_cls=_StubHTTPException,
            html_response_cls=object,
            response_cls=_StubBinaryResponse,
            json_response_cls=_StubJsonResponse,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_contract_routes_registered_with_expected_auth(self) -> None:
        expected_v1 = {
            ("GET", "/api/v1/status"),
            ("GET", "/api/v1/quality/summary"),
            ("GET", "/api/v1/offers"),
            ("GET", "/api/v1/offers/{offer_id}"),
            ("PATCH", "/api/v1/offers/{offer_id}/status"),
            ("GET", "/api/v1/offers/{offer_id}/letter"),
            ("GET", "/api/v1/offers/{offer_id}/letter.pdf"),
            ("GET", "/api/v1/kits"),
            ("GET", "/api/v1/applications"),
            ("POST", "/api/v1/applications"),
            ("POST", "/api/v1/applications/manual"),
            ("DELETE", "/api/v1/applications/manual/{offer_id}"),
            ("GET", "/api/v1/followups"),
            ("GET", "/api/v1/analytics"),
            ("GET", "/api/v1/runs"),
            ("POST", "/api/v1/runs/daily"),
            ("POST", "/api/v1/runs/sync"),
            ("GET", "/api/v1/runs/{run_id}"),
            ("GET", "/api/v1/interview-prep/{offer_id}"),
            ("GET", "/api/v1/setup"),
            ("PUT", "/api/v1/setup"),
        }
        self.assertIn(("GET", "/healthz"), self.stub.routes)
        self.assertNotIn("dependencies", self.stub.route_meta[("GET", "/healthz")])
        self.assertIn(("GET", "/"), self.stub.routes)
        for route in expected_v1:
            self.assertIn(route, self.stub.routes, f"Route manquante: {route}")
            self.assertTrue(
                self.stub.route_meta[route].get("dependencies"),
                f"Authentification requise sur {route}",
            )

    def test_healthz_status_and_quality_contract(self) -> None:
        health = self.stub.routes[("GET", "/healthz")]()
        self.assertEqual(health.service, "career-copilot-fr")
        self.assertEqual(health.status, "ok")
        self.assertEqual(health.checks.sqlite_wal.status, "ok")
        self.assertEqual(health.checks.migrations.status, "ok")
        self.assertGreaterEqual(health.checks.migrations.user_version, 4)

        hw_dir = self.data_dir / "hellowork"
        hw_dir.mkdir(parents=True, exist_ok=True)
        stale_ts = (datetime.now().astimezone() - timedelta(hours=40)).isoformat(timespec="seconds")
        (hw_dir / "last-run.json").write_text(
            json.dumps(
                {
                    "last_run_at": stale_ts,
                    "last_auto_success_at": stale_ts,
                    "last_summary": {
                        "lm_generated": 2,
                        "lm_failed": 1,
                        "errors": ["lettres IA: 1"],
                    },
                }
            ),
            encoding="utf-8",
        )
        status = self.stub.routes[("GET", "/api/v1/status")]()
        self.assertTrue(status.db_ok)
        self.assertEqual(status.offers_active, 3)
        self.assertEqual(status.last_run_at, stale_ts)
        self.assertEqual(status.last_summary.lm_failed, 1)

        quality = self.stub.routes[("GET", "/api/v1/quality/summary")]()
        self.assertEqual(quality.metrics.offers, 3)
        kinds = {issue.kind for issue in quality.issues}
        self.assertIn("hellowork_lm_failure", kinds)
        self.assertIn("hellowork_cycle_stale", kinds)

        with patch.object(self.service, "_schema_info", side_effect=sqlite3.OperationalError("io")):
            unhealthy = self.stub.routes[("GET", "/healthz")]()
        self.assertEqual(unhealthy.status_code, 503)
        self.assertEqual(unhealthy.content["status"], "error")

    def test_offers_filtering_detail_letter_pdf_and_kits(self) -> None:
        stages = self.stub.routes[("GET", "/api/v1/offers")](track="stage")
        self.assertEqual([item.id for item in stages.items], ["offer-101"])
        self.assertTrue(stages.items[0].is_stage)
        self.assertFalse(stages.items[0].is_alternance)
        self.assertEqual(stages.items[0].ats_url, "https://ats.example.org/apply/101")

        alts = self.stub.routes[("GET", "/api/v1/offers")](track="alternance")
        self.assertEqual([item.id for item in alts.items], ["offer-alt"])
        self.assertTrue(alts.items[0].is_alternance)

        jobs = self.stub.routes[("GET", "/api/v1/offers")](track="job")
        self.assertEqual([item.id for item in jobs.items], ["offer-job"])

        exact = self.stub.routes[("GET", "/api/v1/offers")](
            company="exemple infra sas", exact_company=True, limit=2
        )
        self.assertEqual([item.id for item in exact.items], ["offer-101"])
        q_hit = self.stub.routes[("GET", "/api/v1/offers")](q="DevSecOps")
        self.assertEqual([item.id for item in q_hit.items], ["offer-alt"])

        detail = self.stub.routes[("GET", "/api/v1/offers/{offer_id}")]("offer-101")
        self.assertIn("Linux", detail.description)
        self.assertEqual(detail.partner_url, "https://ats.example.org/apply/101")
        with self.assertRaises(_StubHTTPException) as missing:
            self.stub.routes[("GET", "/api/v1/offers/{offer_id}")]("missing")
        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(getattr(missing.exception, "code", ""), "offer_not_found")

        # Letter JSON + PDF
        lettres_dir = self.data_dir / "lettres"
        lettres_dir.mkdir(parents=True, exist_ok=True)
        url_key = hashlib.sha256(b"https://example.org/jobs/101").hexdigest()[:24]
        (lettres_dir / f"{url_key}.json").write_text(
            json.dumps({"letter": "Madame, Monsieur,\nCandidature test."}), encoding="utf-8"
        )
        (lettres_dir / f"{url_key}.pdf").write_bytes(b"%PDF-1.4\n%test\n")

        letter_res = self.stub.routes[("GET", "/api/v1/offers/{offer_id}/letter")]("offer-101")
        self.assertIn("Candidature test", letter_res.letter)
        pdf_res = self.stub.routes[("GET", "/api/v1/offers/{offer_id}/letter.pdf")]("offer-101")
        self.assertEqual(pdf_res.media_type, "application/pdf")
        self.assertTrue(pdf_res.content.startswith(b"%PDF-1.4"))
        self.assertIn('filename="lettre-offer-101.pdf"', pdf_res.headers["Content-Disposition"])

        with self.assertRaises(_StubHTTPException) as no_letter:
            self.stub.routes[("GET", "/api/v1/offers/{offer_id}/letter")]("offer-alt")
        self.assertEqual(no_letter.exception.status_code, 404)
        self.assertEqual(getattr(no_letter.exception, "code", ""), "letter_not_found")

        # Kits ready_only filter
        cv_file = self.data_dir / "cv.pdf"
        cv_file.write_bytes(b"%PDF-1.4")
        dossier_file = self.data_dir / "dossier.json"
        dossier_file.write_text('{"ok": true}', encoding="utf-8")
        kits_store.save_kit(
            self.service.handle,
            "offer-101",
            "Candidature Stage",
            lettres_dir / f"{url_key}.pdf",
            cv_file,
            dossier_file,
        )
        kits_store.save_kit(self.service.handle, "offer-alt", "Partiel", None, None, dossier_file)
        all_kits = self.stub.routes[("GET", "/api/v1/kits")](ready_only=False)
        ready_kits = self.stub.routes[("GET", "/api/v1/kits")](ready_only=True)
        self.assertEqual(all_kits.total, 2)
        self.assertEqual(ready_kits.total, 1)
        self.assertEqual(ready_kits.items[0].company, "Exemple Infra SAS")

    def test_manual_applications_withdraw_followups_analytics_and_runs(self) -> None:
        # Declare manual application (201) then idempotent repeat (200)
        created = self.stub.routes[("POST", "/api/v1/applications/manual")](
            ManualApplicationRequest(
                offer_id="offer-101",
                channel="telegram-manuel",
                note="Déclaré via Telegram",
            )
        )
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.content["changed"])
        self.assertTrue(created.content["application"]["manual"])

        dup = self.stub.routes[("POST", "/api/v1/applications/manual")](
            ManualApplicationRequest(url="https://example.org/jobs/101")
        )
        self.assertEqual(dup.status_code, 200)
        self.assertFalse(dup.content["changed"])
        self.assertEqual(dup.content["reason"], "already_recorded")

        # List applications includes items + kits
        apps = self.stub.routes[("GET", "/api/v1/applications")]()
        self.assertEqual(apps.total, 1)
        self.assertEqual(apps.items[0].url, "https://example.org/jobs/101")

        # Withdraw manual succeeds (200)
        withdrawn = self.stub.routes[("DELETE", "/api/v1/applications/manual/{offer_id}")](
            "offer-101"
        )
        self.assertTrue(withdrawn.changed)
        self.assertEqual(withdrawn.status, "new")

        # Non-manual application cannot be withdrawn (409 not_manual_application)
        old_applied = (datetime.now().astimezone() - timedelta(days=10)).isoformat(
            timespec="seconds"
        )
        apps_store.confirm(
            self.service.handle,
            "offer-alt",
            channel="hellowork-auto",
            applied_at=old_applied,
            proof_kind="authenticated_receipt",
            proof_reference="receipt-1",
        )
        with self.assertRaises(_StubHTTPException) as conflict:
            self.stub.routes[("DELETE", "/api/v1/applications/manual/{offer_id}")]("offer-alt")
        self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(getattr(conflict.exception, "code", ""), "not_manual_application")

        # Followups (10 days old -> due)
        followups = self.stub.routes[("GET", "/api/v1/followups")](due_only=True)
        self.assertEqual(followups.count_due, 1)
        self.assertEqual(followups.candidates[0].offer_id, "offer-alt")
        self.assertGreaterEqual(followups.candidates[0].days_since_application, 9)

        # Analytics (zero systemd coupling)
        analytics = self.stub.routes[("GET", "/api/v1/analytics")]()
        self.assertEqual(analytics.kpis.offers_total, 3)
        self.assertEqual(analytics.kpis.applications_total, 1)
        self.assertEqual(analytics.freshness[0].label, "HelloWork")

        # Runs: daily 202 + duplicate 409 + sync + get_run + list_runs
        daily_res = self.stub.routes[("POST", "/api/v1/runs/daily")](
            DailyRunTriggerRequest(auto_submit=False)
        )
        self.assertEqual(daily_res.status, "running")
        with self.assertRaises(_StubHTTPException) as active_err:
            self.stub.routes[("POST", "/api/v1/runs/daily")](DailyRunTriggerRequest())
        self.assertEqual(active_err.exception.status_code, 409)
        self.assertEqual(getattr(active_err.exception, "code", ""), "run_already_active")

        sync_res = self.stub.routes[("POST", "/api/v1/runs/sync")](
            SyncRunTriggerRequest(source="imap")
        )
        self.assertEqual(sync_res.status, "success")
        self.assertEqual(sync_res.synced_messages, 3)

        run_detail = self.stub.routes[("GET", "/api/v1/runs/{run_id}")](sync_res.run_id)
        self.assertEqual(run_detail.kind, "sync")
        self.assertEqual(run_detail.synced_messages, 3)

        runs = self.stub.routes[("GET", "/api/v1/runs")](limit=8)
        self.assertEqual(len(runs.runs), 2)

        with self.assertRaises(_StubHTTPException) as missing_run:
            self.stub.routes[("GET", "/api/v1/runs/{run_id}")](9999)
        self.assertEqual(missing_run.exception.status_code, 404)
        self.assertEqual(getattr(missing_run.exception, "code", ""), "run_not_found")

    def test_setup_interview_prep_and_create_app_behavior(self) -> None:
        example = build_example_profile_v2(cities=("lyon",))
        updated = self.stub.routes[("PUT", "/api/v1/setup")](SetupProfileUpdateRequest(**example))
        self.assertTrue(updated.configured)
        prep = self.stub.routes[("GET", "/api/v1/interview-prep/{offer_id}")]("offer-101")
        self.assertEqual(prep.company, "Exemple Infra SAS")
        patched = self.stub.routes[("PATCH", "/api/v1/offers/{offer_id}/status")](
            "offer-101", OfferStatusUpdate(status="shortlist", note="Prioritaire")
        )
        self.assertEqual(patched.status, "shortlist")
        created = self.stub.routes[("POST", "/api/v1/applications")](
            ApplicationCreateRequest(offer_id="offer-101", channel="candidature-manuelle")
        )
        self.assertEqual(created.offer_id, "offer-101")

        token = "T" * 40
        if FASTAPI_AVAILABLE:
            app = create_app(data_dir=self.data_dir, token=token)
            self.assertEqual(app.title, "Career Copilot FR API")
        else:
            with self.assertRaises(RuntimeError) as ctx:
                create_app(data_dir=self.data_dir, token=token)
            self.assertIn("uv sync", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

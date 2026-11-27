"""SQLite legacy unification and RGPD portability/erasure tools."""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from career_copilot.sources.deps import SourcesDeps

LOG = logging.getLogger("career_copilot.sources.rgpd")

_SQLITE_MIGRATION_ERRORS = (KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error)

_PURGE_FILES: tuple[str, ...] = (
    "hellowork.db",
    "candidatures.db",
    "Suivi-candidatures.xlsx",
    "ai_cache.json",
    "ai_usage.json",
)
_PURGE_DIRS: tuple[str, ...] = ("hellowork/kits", "letters")


def _migrate_target_row(row_d: dict[str, Any], deps: SourcesDeps) -> tuple[bool, bool]:
    url = str(row_d.get("url") or "").strip()
    key = str(row_d.get("id") or url or "").strip()
    if not key:
        return False, False
    oid = str(row_d.get("hw_offer_id") or "").strip() or (
        key
        if re.fullmatch(r"[A-Za-z0-9._-]{1,120}", key)
        else deps.source_common.stable_id("legacy", key)
    )
    if deps.hw_store.get(oid) or (url and deps.hw_store.by_url(url)):
        return False, False

    camp = str(row_d.get("campaign") or "stage").lower()
    contract = (
        "Alternance" if camp == "alternance" else ("job_etudiant" if camp == "job" else "Stage")
    )
    title_str = (
        str(row_d.get("title") or "").strip() or f"{contract} — {row_d.get('name') or 'Entreprise'}"
    )
    off = deps.hw_offers.Offer(
        id=oid,
        url=url
        or (
            f"mailto:{row_d.get('email')}" if row_d.get("email") else f"https://legacy.local/{oid}"
        ),
        title=title_str,
        company=str(row_d.get("name") or "Entreprise"),
        city=str(row_d.get("city") or ""),
        department=deps.source_common.extract_department(str(row_d.get("city") or "")),
        contract=contract,
        description=f"Source : {row_d.get('detail') or 'locale'}",
        apply_mode="email" if row_d.get("email") else "manual",
    )
    deps.geo.resolve(off, geocoder=lambda c, d="": deps.geo.geocode(c, d, network=False))
    sc = deps.scoring.evaluate(off)
    deps.hw_store.save_offer(off, sc)

    migrated_app = False
    if str(row_d.get("status") or "") in ("emailed", "relanced"):
        try:
            deps.hw_store.add_application(
                offer_id=oid,
                company=off.company,
                title=off.title,
                channel="email-smtp",
                evidence="Migré depuis candidatures.db",
                applied_at=str(row_d.get("emailed_at") or row_d.get("first_seen") or ""),
                mark_offer=True,
                proof_kind="smtp_accepted",
                proof_reference=key,
            )
            migrated_app = True
        except _SQLITE_MIGRATION_ERRORS as exc:
            LOG.debug("Migration candidature ignorée (%s): %s", oid, exc)
    return True, migrated_app


def unify_sqlite_databases(deps: SourcesDeps) -> dict[str, int]:
    """Non-destructively migrate targets and applications from ``candidatures.db`` into ``hellowork.db``."""
    deps.hw_store.init()
    legacy_db = deps.config.DB_PATH
    if not legacy_db.is_file() or legacy_db.is_symlink():
        return {"migrated_offers": 0, "migrated_applications": 0}

    migrated_offers = 0
    migrated_apps = 0
    try:
        with closing(sqlite3.connect(legacy_db, timeout=5.0)) as conn:
            conn.row_factory = sqlite3.Row
            tables = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "targets" in tables:
                for row in conn.execute("SELECT * FROM targets").fetchall():
                    added_offer, added_app = _migrate_target_row(dict(row), deps)
                    if added_offer:
                        migrated_offers += 1
                    if added_app:
                        migrated_apps += 1
    except _SQLITE_MIGRATION_ERRORS as exc:
        LOG.warning("Migration non destructive candidatures.db ignorée : %s", exc)
    return {
        "migrated_offers": migrated_offers,
        "migrated_applications": migrated_apps,
    }


def export_rgpd_archive(deps: SourcesDeps, data_dir: Path | None = None) -> dict[str, Any]:
    """Build a complete JSON portability archive of local candidate data (RGPD Art. 20)."""
    cfg = deps.candidate_config.get_profile()
    deps.hw_store.init()
    offers = [dict(r) for r in deps.hw_store.list_offers(min_score=0, limit=1000)]
    applications: list[dict[str, Any]] = []
    try:
        db_file = (Path(data_dir) if data_dir else deps.config.DATA_DIR) / "hellowork.db"
        if db_file.is_file():
            with closing(sqlite3.connect(db_file, timeout=5.0)) as conn:
                conn.row_factory = sqlite3.Row
                applications = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM applications ORDER BY applied_at DESC"
                    ).fetchall()
                ]
    except (OSError, sqlite3.Error) as exc:
        LOG.debug("Lecture applications RGPD ignorée: %s", exc)
    return {
        "ok": True,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "schema_version": 2,
        "profile": cfg.to_dict() if cfg.configured else None,
        "offers_count": len(offers),
        "applications_count": len(applications),
        "offers": offers,
        "applications": applications,
    }


def purge_rgpd_data(deps: SourcesDeps, data_dir: Path | None = None) -> dict[str, Any]:
    """Delete local personal data on explicit user request (RGPD Art. 17 right to erasure)."""
    target_dir = Path(data_dir) if data_dir is not None else deps.config.DATA_DIR
    prof_path = deps.candidate_config.profile_path()
    removed: list[str] = []

    if prof_path.is_file() and not prof_path.is_symlink():
        prof_path.unlink(missing_ok=True)
        removed.append(prof_path.name)

    for fname in _PURGE_FILES:
        fpath = target_dir / fname
        if fpath.is_file() and not fpath.is_symlink():
            fpath.unlink(missing_ok=True)
            removed.append(fname)

    for sub in _PURGE_DIRS:
        sdir = target_dir / sub
        if sdir.is_dir() and not sdir.is_symlink():
            shutil.rmtree(sdir, ignore_errors=True)
            removed.append(sub)

    deps.candidate_config.reload_profile()
    deps.hw_store.init()
    return {"ok": True, "removed": removed}

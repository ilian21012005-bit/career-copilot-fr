"""Backward-compatible re-export shim for ``career_copilot.sources``.

All source plugin registry logic, HITL URL/text offer importing, local CV
parsing, SQLite unification, and RGPD export/erasure tools now live in
``src/career_copilot/sources/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import candidate_config
import config
import filters
import presets
import public_network
import source_common
from hellowork import geo
from hellowork import offer as hw_offers
from hellowork import score as scoring
from hellowork import store as hw_store

_SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.sources import (
    SourcePlugin,
    SourcesDeps,
    build_commercial_safe_plugins,
    build_oss_local_only_plugins,
)
from career_copilot.sources import (
    detect_preset_and_skills as _detect_preset_and_skills_impl,
)
from career_copilot.sources import (
    export_rgpd_archive as _export_rgpd_archive_impl,
)
from career_copilot.sources import (
    extract_text_from_pdf_bytes as _extract_text_from_pdf_bytes,
)
from career_copilot.sources import (
    import_offer_from_url_or_text as _import_offer_impl,
)
from career_copilot.sources import (
    infer_imported_contract as _infer_imported_contract_impl,
)
from career_copilot.sources import (
    is_commercial_edition as _is_commercial_edition_impl,
)
from career_copilot.sources import (
    list_sources_status as _list_sources_status_impl,
)
from career_copilot.sources import (
    parse_cv_to_profile_draft as _parse_cv_to_profile_draft_impl,
)
from career_copilot.sources import (
    purge_rgpd_data as _purge_rgpd_data_impl,
)
from career_copilot.sources import (
    run_discovery_scan as _run_discovery_scan_impl,
)
from career_copilot.sources import (
    unify_sqlite_databases as _unify_sqlite_databases_impl,
)

LOG = logging.getLogger("sources_registry")


def _fetch_csp(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import csp_offres

    return csp_offres.search(env, campaign=campaign)


def _fetch_france_travail(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import offres

    cfg = candidate_config.get_profile()
    queries = (
        config.ADZUNA_JOB_QUERIES[:4]
        if campaign == "job"
        else list(cfg.adzuna_stage_queries[:4] or ("stage",))
    )
    if campaign == "alternance":
        queries = [q if "alternance" in q.lower() else f"alternance {q}" for q in queries]
    zones = config.ZONES.get(campaign) or config.ZONES.get("stage", [])
    results: list[dict[str, Any]] = []
    for zone in zones:
        for query in queries:
            for item in offres.search(env, query, zone):
                item["campaign"] = campaign
                if campaign == "alternance":
                    item["alternance"] = True
                results.append(item)
    return results


def _fetch_lba(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import lba

    if campaign != "alternance":
        return []
    cfg = candidate_config.get_profile()
    zones = config.ZONES.get("alternance") or config.ZONES.get("stage", [])
    results: list[dict[str, Any]] = []
    for zone in zones:
        for item in lba.search(env, zone, romes=cfg.preset.rome_codes):
            item["campaign"] = "alternance"
            item["alternance"] = True
            results.append(item)
    return results


def _fetch_workday(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import workday

    return workday.search(env, campaign=campaign)


def _fetch_smartrecruiters(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import smartrecruiters

    return smartrecruiters.search(env, campaign=campaign)


def _fetch_teamtailor(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import teamtailor

    return teamtailor.search(env, campaign=campaign)


def _fetch_recruitee(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import recruitee

    return recruitee.search(env, campaign=campaign)


def _fetch_ats_public(env: dict[str, str], campaign: str) -> list[dict[str, Any]]:
    import ats_public

    if hasattr(ats_public, "search"):
        return ats_public.search(env, campaign=campaign)
    return []


def _commercial_safe_plugins() -> tuple[SourcePlugin, ...]:
    import ats_public
    import csp_offres
    import recruitee
    import smartrecruiters
    import teamtailor
    import workday

    return build_commercial_safe_plugins(
        csp_offres=csp_offres,
        workday=workday,
        smartrecruiters=smartrecruiters,
        teamtailor=teamtailor,
        recruitee=recruitee,
        ats_public=ats_public,
        fetch_csp=_fetch_csp,
        fetch_france_travail=_fetch_france_travail,
        fetch_workday=_fetch_workday,
        fetch_smartrecruiters=_fetch_smartrecruiters,
        fetch_teamtailor=_fetch_teamtailor,
        fetch_recruitee=_fetch_recruitee,
        fetch_ats_public=_fetch_ats_public,
    )


def _oss_local_only_plugins() -> tuple[SourcePlugin, ...]:
    import adzuna
    import apec
    import lba
    import wttj
    from hellowork import jobspy_source

    return build_oss_local_only_plugins(
        lba=lba,
        adzuna=adzuna,
        wttj=wttj,
        apec=apec,
        jobspy_source=jobspy_source,
        get_profile_contracts=lambda: candidate_config.get_profile().contracts,
        fetch_lba=_fetch_lba,
    )


def get_source_plugins() -> tuple[SourcePlugin, ...]:
    return (*_commercial_safe_plugins(), *_oss_local_only_plugins())


def _deps() -> SourcesDeps:
    return SourcesDeps(
        config=config,
        candidate_config=candidate_config,
        filters=filters,
        presets=presets,
        public_network=public_network,
        source_common=source_common,
        geo=geo,
        hw_offers=hw_offers,
        scoring=scoring,
        hw_store=hw_store,
        get_plugins=get_source_plugins,
    )


def is_commercial_edition(env: dict[str, str] | None = None) -> bool:
    return _is_commercial_edition_impl(_deps(), env)


def list_sources_status(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    return _list_sources_status_impl(_deps(), env)


def unify_sqlite_databases() -> dict[str, int]:
    return _unify_sqlite_databases_impl(_deps())


def _infer_imported_contract(raw_contract: str, raw_title: str, raw_text: str, cfg: Any) -> str:
    return _infer_imported_contract_impl(raw_contract, raw_title, raw_text, cfg, filters._fold)


def import_offer_from_url_or_text(payload: dict[str, Any]) -> dict[str, Any]:
    return _import_offer_impl(payload, _deps())


def run_discovery_scan(
    env: dict[str, str] | None = None,
    *,
    commercial_safe: bool | None = None,
    campaigns: list[str] | None = None,
) -> dict[str, Any]:
    return _run_discovery_scan_impl(
        _deps(),
        env,
        commercial_safe=commercial_safe,
        campaigns=campaigns,
        unify_fn=unify_sqlite_databases,
    )


def _detect_preset_and_skills(folded_text: str, preset_hint: str) -> tuple[str, list[str]]:
    return _detect_preset_and_skills_impl(folded_text, preset_hint, presets, filters._fold)


def parse_cv_to_profile_draft(
    *,
    raw_text: str = "",
    pdf_base64: str = "",
    preset_hint: str = "",
) -> dict[str, Any]:
    return _parse_cv_to_profile_draft_impl(
        _deps(),
        raw_text=raw_text,
        pdf_base64=pdf_base64,
        preset_hint=preset_hint,
    )


def export_rgpd_archive(data_dir: Path | None = None) -> dict[str, Any]:
    return _export_rgpd_archive_impl(_deps(), data_dir=data_dir)


def purge_rgpd_data(data_dir: Path | None = None) -> dict[str, Any]:
    return _purge_rgpd_data_impl(_deps(), data_dir=data_dir)


__all__ = [
    "LOG",
    "SourcePlugin",
    "_commercial_safe_plugins",
    "_detect_preset_and_skills",
    "_extract_text_from_pdf_bytes",
    "_fetch_ats_public",
    "_fetch_csp",
    "_fetch_france_travail",
    "_fetch_lba",
    "_fetch_recruitee",
    "_fetch_smartrecruiters",
    "_fetch_teamtailor",
    "_fetch_workday",
    "_infer_imported_contract",
    "_oss_local_only_plugins",
    "export_rgpd_archive",
    "get_source_plugins",
    "import_offer_from_url_or_text",
    "is_commercial_edition",
    "list_sources_status",
    "parse_cv_to_profile_draft",
    "purge_rgpd_data",
    "run_discovery_scan",
    "unify_sqlite_databases",
]

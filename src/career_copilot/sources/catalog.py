"""Source plugin catalog, edition compliance checks, and discovery runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from career_copilot.sources.deps import SourcePlugin, SourcesDeps

_DISCOVERY_ERRORS = (
    ImportError,
    KeyError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    sqlite3.Error,
)


def is_commercial_edition(deps: SourcesDeps, env: dict[str, str] | None = None) -> bool:
    """Return ``True`` when strict commercial mode is active (``COMMERCIAL_SAFE=1``)."""
    return bool(deps.config.is_commercial_safe(env))


def build_commercial_safe_plugins(
    *,
    csp_offres: Any,
    workday: Any,
    smartrecruiters: Any,
    teamtailor: Any,
    recruitee: Any,
    ats_public: Any,
    fetch_csp: Callable[[dict[str, str], str], list[dict[str, Any]]],
    fetch_france_travail: Callable[[dict[str, str], str], list[dict[str, Any]]],
    fetch_workday: Callable[[dict[str, str], str], list[dict[str, Any]]],
    fetch_smartrecruiters: Callable[[dict[str, str], str], list[dict[str, Any]]],
    fetch_teamtailor: Callable[[dict[str, str], str], list[dict[str, Any]]],
    fetch_recruitee: Callable[[dict[str, str], str], list[dict[str, Any]]],
    fetch_ats_public: Callable[[dict[str, str], str], list[dict[str, Any]]],
) -> tuple[SourcePlugin, ...]:
    """Build the tuple of commercial-safe offer discovery plugins."""
    return (
        SourcePlugin(
            id="url_import",
            label="Import URL / texte / bookmarklet 1-clic (Human-in-the-loop)",
            commercial_safe=True,
            contracts=("stage", "alternance", "job"),
            requires_credentials=False,
            legal_notice="Saisie explicite par l'utilisateur — 100 % conforme CGU & RGPD.",
            is_enabled=lambda _env: True,
            fetch_offers=lambda _env, _c: [],
        ),
        SourcePlugin(
            id="csp",
            label="Choisir le Service Public (Open Data Etalab 2.0)",
            commercial_safe=True,
            contracts=("stage", "alternance"),
            requires_credentials=False,
            legal_notice=(
                "Licence Ouverte Etalab 2.0 (lov2) — usage OSS et commercial autorisé "
                "avec mention de la source."
            ),
            is_enabled=lambda env: bool(csp_offres.enabled(env)),
            fetch_offers=fetch_csp,
        ),
        SourcePlugin(
            id="francetravail",
            label="France Travail Offres v2",
            commercial_safe=True,
            contracts=("stage", "alternance", "job"),
            requires_credentials=True,
            legal_notice=(
                "Licence partenaire France Travail — mention obligatoire et purge "
                "des offres expirées."
            ),
            is_enabled=lambda env: bool(
                str((env or {}).get("FT_CLIENT_ID") or "").strip()
                and str((env or {}).get("FT_CLIENT_SECRET") or "").strip()
            ),
            fetch_offers=fetch_france_travail,
        ),
        SourcePlugin(
            id="workday",
            label="Portails publics Workday CXS",
            commercial_safe=True,
            contracts=("stage", "alternance", "job"),
            requires_credentials=False,
            legal_notice="Flux JSON carrières publics lecture seule avec rate-limiting.",
            is_enabled=lambda env: bool(workday.enabled(env)),
            fetch_offers=fetch_workday,
        ),
        SourcePlugin(
            id="smartrecruiters",
            label="API publique SmartRecruiters",
            commercial_safe=True,
            contracts=("stage", "alternance", "job"),
            requires_credentials=False,
            legal_notice="API Posting publique SmartRecruiters lecture seule.",
            is_enabled=lambda env: bool(smartrecruiters.enabled(env)),
            fetch_offers=fetch_smartrecruiters,
        ),
        SourcePlugin(
            id="teamtailor",
            label="Flux RSS publics Teamtailor",
            commercial_safe=True,
            contracts=("stage", "alternance", "job"),
            requires_credentials=False,
            legal_notice="Flux RSS publics Teamtailor lecture seule.",
            is_enabled=lambda env: bool(teamtailor.enabled(env)),
            fetch_offers=fetch_teamtailor,
        ),
        SourcePlugin(
            id="recruitee",
            label="API publique Recruitee",
            commercial_safe=True,
            contracts=("stage", "alternance", "job"),
            requires_credentials=False,
            legal_notice="Endpoints JSON publics `/api/offers/` Recruitee.",
            is_enabled=lambda env: bool(recruitee.enabled(env)),
            fetch_offers=fetch_recruitee,
        ),
        SourcePlugin(
            id="ats_public",
            label="API publiques Greenhouse / Lever / Ashby",
            commercial_safe=True,
            contracts=("stage", "alternance"),
            requires_credentials=False,
            legal_notice="Endpoints JSON carrières publics lecture seule.",
            is_enabled=lambda env: bool(ats_public.enabled(env)),
            fetch_offers=fetch_ats_public,
        ),
    )


def build_oss_local_only_plugins(
    *,
    lba: Any,
    adzuna: Any,
    wttj: Any,
    apec: Any,
    jobspy_source: Any,
    get_profile_contracts: Callable[[], tuple[str, ...]],
    fetch_lba: Callable[[dict[str, str], str], list[dict[str, Any]]],
) -> tuple[SourcePlugin, ...]:
    """Build the tuple of OSS-local-only plugins blocked in commercial mode."""
    return (
        SourcePlugin(
            id="lba",
            label="La Bonne Alternance (DGEFP / beta.gouv.fr)",
            commercial_safe=False,
            contracts=("alternance",),
            requires_credentials=False,
            legal_notice=(
                "Art. 5.2 CGU LBA : réservé aux usages non lucratifs "
                "(activé uniquement en mode OSS local)."
            ),
            is_enabled=lambda env: bool(lba.enabled(env, contracts=get_profile_contracts())),
            fetch_offers=fetch_lba,
        ),
        SourcePlugin(
            id="adzuna",
            label="Adzuna API (BYO-Key)",
            commercial_safe=False,
            contracts=("stage", "alternance", "job"),
            requires_credentials=True,
            legal_notice="Clé développeur gratuite limitée à un usage personnel non commercial.",
            is_enabled=lambda env: bool(adzuna.enabled(env)),
            fetch_offers=lambda _env, _c: [],
        ),
        SourcePlugin(
            id="jooble",
            label="Jooble API (BYO-Key)",
            commercial_safe=False,
            contracts=("job",),
            requires_credentials=True,
            legal_notice="Clé gratuite soumise au quota journalier Jooble.",
            is_enabled=lambda env: bool(str((env or {}).get("JOOBLE_KEY") or "").strip()),
            fetch_offers=lambda _env, _c: [],
        ),
        SourcePlugin(
            id="wttj",
            label="Welcome to the Jungle (Algolia local)",
            commercial_safe=False,
            contracts=("stage", "alternance"),
            requires_credentials=True,
            legal_notice="Usage personnel local uniquement (désactivé en mode commercial).",
            is_enabled=lambda env: bool(wttj.enabled(env)),
            fetch_offers=lambda _env, _c: [],
        ),
        SourcePlugin(
            id="apec",
            label="APEC (Playwright local)",
            commercial_safe=False,
            contracts=("stage", "alternance"),
            requires_credentials=False,
            legal_notice="Usage personnel local uniquement (désactivé en mode commercial).",
            is_enabled=lambda env: bool(apec.enabled(env)),
            fetch_offers=lambda _env, _c: [],
        ),
        SourcePlugin(
            id="jobspy",
            label="JobSpy (Agrégateur local optionnel)",
            commercial_safe=False,
            contracts=("stage", "alternance"),
            requires_credentials=False,
            legal_notice="Usage personnel local uniquement (désactivé en mode commercial).",
            is_enabled=lambda _env: bool(jobspy_source.available()),
            fetch_offers=lambda _env, _c: [],
        ),
    )


def list_sources_status(
    deps: SourcesDeps, env: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Return status and commercial compliance metadata for every registered source plugin."""
    active_env = dict(deps.config.load_env())
    if env:
        active_env.update(env)
    comm_safe = is_commercial_edition(deps, active_env)
    items: list[dict[str, Any]] = []
    for plugin in deps.get_plugins():
        allowed_in_edition = plugin.commercial_safe if comm_safe else True
        enabled_now = bool(allowed_in_edition and plugin.is_enabled(active_env))
        items.append(
            {
                "id": plugin.id,
                "label": plugin.label,
                "commercial_safe": plugin.commercial_safe,
                "contracts": list(plugin.contracts),
                "requires_credentials": plugin.requires_credentials,
                "legal_notice": plugin.legal_notice,
                "enabled": enabled_now,
                "blocked_by_commercial_mode": bool(comm_safe and not plugin.commercial_safe),
            }
        )
    return items


def _ingest_campaign_offers(
    deps: SourcesDeps, campaign: str, raw_offers: list[dict[str, Any]]
) -> int:
    if campaign == "alternance":
        return int(deps.source_common.ingest_alternance_offers_to_store(raw_offers))
    if campaign == "job":
        return int(deps.source_common.ingest_job_offers_to_store(raw_offers))
    return int(deps.source_common.ingest_stage_offers_to_store(raw_offers))


def run_discovery_scan(
    deps: SourcesDeps,
    env: dict[str, str] | None = None,
    *,
    commercial_safe: bool | None = None,
    campaigns: list[str] | None = None,
    unify_fn: Callable[[], dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Run multi-source discovery via the plugin catalog without Gmail or Chrome."""
    active_env = dict(deps.config.load_env())
    if env:
        active_env.update(env)
    if commercial_safe is not None:
        active_env["COMMERCIAL_SAFE"] = "1" if commercial_safe else "0"
    comm_mode = is_commercial_edition(deps, active_env)
    cfg = deps.candidate_config.get_profile()
    target_campaigns = tuple(campaigns or cfg.contracts or ("stage",))

    checked_sources: list[str] = []
    skipped_commercial: list[str] = []
    errors: list[str] = []
    total_ingested = 0

    for plugin in deps.get_plugins():
        if comm_mode and not plugin.commercial_safe:
            skipped_commercial.append(plugin.id)
            continue
        if not plugin.is_enabled(active_env):
            continue
        checked_sources.append(plugin.id)
        for camp in target_campaigns:
            if camp not in plugin.contracts:
                continue
            try:
                raw_offers = plugin.fetch_offers(active_env, camp)
                if raw_offers:
                    total_ingested += _ingest_campaign_offers(deps, camp, raw_offers)
            except _DISCOVERY_ERRORS as exc:
                errors.append(f"{plugin.id} ({camp}): {type(exc).__name__}")

    migration = unify_fn() if unify_fn is not None else {"migrated_offers": 0}
    return {
        "ok": True,
        "commercial_safe": comm_mode,
        "campaigns": list(target_campaigns),
        "checked_sources": checked_sources,
        "skipped_non_commercial": skipped_commercial,
        "added_offers": total_ingested,
        "migrated_from_legacy": migration["migrated_offers"],
        "errors": errors,
    }

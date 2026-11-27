"""Unified source plugins, HITL importer, local CV parser, and RGPD tools."""

from __future__ import annotations

from career_copilot.sources.catalog import (
    build_commercial_safe_plugins,
    build_oss_local_only_plugins,
    is_commercial_edition,
    list_sources_status,
    run_discovery_scan,
)
from career_copilot.sources.cv_parser import (
    detect_preset_and_skills,
    extract_text_from_pdf_bytes,
    parse_cv_to_profile_draft,
)
from career_copilot.sources.deps import SourcePlugin, SourcesDeps
from career_copilot.sources.importer import (
    import_offer_from_url_or_text,
    infer_imported_contract,
)
from career_copilot.sources.rgpd import (
    export_rgpd_archive,
    purge_rgpd_data,
    unify_sqlite_databases,
)

__all__ = [
    "SourcePlugin",
    "SourcesDeps",
    "build_commercial_safe_plugins",
    "build_oss_local_only_plugins",
    "detect_preset_and_skills",
    "export_rgpd_archive",
    "extract_text_from_pdf_bytes",
    "import_offer_from_url_or_text",
    "infer_imported_contract",
    "is_commercial_edition",
    "list_sources_status",
    "parse_cv_to_profile_draft",
    "purge_rgpd_data",
    "run_discovery_scan",
    "unify_sqlite_databases",
]

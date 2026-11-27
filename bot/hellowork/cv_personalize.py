"""Backward-compatible re-export shim for ``career_copilot.cv``.

All ATS 1-page HTML CV rendering, track detection, skill filtering, and PDF
compilation logic now live in ``src/career_copilot/cv/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import candidate_config
import presets
from private_storage import (
    ensure_private_directory,
    protect_private_file,
    write_private_text,
)

from .offer import Offer

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.cv import (
    ALTERNANCE_TOKENS as _ALTERNANCE_TOKENS,
)
from career_copilot.cv import (
    COMPACT_CSS,
    CSS,
    CvDeps,
    Track,
    pdf_page_count,
)
from career_copilot.cv import (
    GUARDRAIL_FACT_PREFIXES as _GUARDRAIL_FACT_PREFIXES,
)
from career_copilot.cv import (
    MONTHS_SHORT_FR as _MONTHS_SHORT_FR,
)
from career_copilot.cv import (
    UPPER_ACRONYMS as _UPPER_ACRONYMS,
)
from career_copilot.cv import (
    build_pdf_for_offer as _build_pdf_for_offer_impl,
)
from career_copilot.cv import (
    detect_track as _detect_track_impl,
)
from career_copilot.cv import (
    escape_html as _e,
)
from career_copilot.cv import (
    filter_skill_block_items as _filter_skill_block_items,
)
from career_copilot.cv import (
    is_alternance_offer as _is_alternance_offer,
)
from career_copilot.cv import (
    is_job_offer as _is_job_offer,
)
from career_copilot.cv import (
    keyword_present as _keyword_present,
)
from career_copilot.cv import (
    offer_blob as _offer_blob,
)
from career_copilot.cv import (
    offer_owned_keywords as _offer_owned_keywords,
)
from career_copilot.cv import (
    parse_date_safe as _parse_date_safe,
)
from career_copilot.cv import (
    pretty_skill as _pretty_skill,
)
from career_copilot.cv import (
    render_cv_document as _render_cv_document_impl,
)
from career_copilot.cv import (
    render_education as _render_education,
)
from career_copilot.cv import (
    render_experiences as _render_experiences,
)
from career_copilot.cv import (
    render_header as _render_header,
)
from career_copilot.cv import (
    render_html as _render_html_impl,
)
from career_copilot.cv import (
    render_html_compact as _render_html_compact_impl,
)
from career_copilot.cv import (
    render_projects as _render_projects,
)
from career_copilot.cv import (
    render_skills_section as _render_skills_section,
)
from career_copilot.cv import (
    render_v1_facts as _render_v1_facts,
)
from career_copilot.cv import (
    resolve_mobility as _resolve_mobility,
)
from career_copilot.cv import (
    score_tracks_for_preset as _score_tracks_for_preset,
)
from career_copilot.cv import (
    select_track_for_cv as _select_track_for_cv_impl,
)
from career_copilot.cv import (
    short_url as _short_url,
)
from career_copilot.cv import (
    tag_relevance as _tag_relevance,
)


def _deps(*, html_to_pdf_fn: Any = None) -> CvDeps:
    return CvDeps(
        get_profile=candidate_config.get_profile,
        get_preset=presets.get_preset,
        default_start_date=candidate_config.DEFAULT_START_DATE,
        default_end_date=candidate_config.DEFAULT_END_DATE,
        default_weeks=candidate_config.DEFAULT_WEEKS,
        ensure_private_directory=ensure_private_directory,
        protect_private_file=protect_private_file,
        write_private_text=write_private_text,
        html_to_pdf_fn=html_to_pdf_fn,
        pdf_page_count_fn=pdf_page_count,
        render_html_fn=render_html,
        render_html_compact_fn=render_html_compact,
        select_track_fn=select_track_for_cv,
    )


def detect_track(offer: Offer) -> str:
    return _detect_track_impl(offer, candidate_config.get_profile)


def select_track_for_cv(offer: Offer) -> str:
    try:
        import ai_client
    except ImportError:
        return detect_track(offer)
    return _select_track_for_cv_impl(
        offer,
        candidate_config.get_profile,
        ask_ai_fn=ai_client.ask_ai,
        prose_model=ai_client.PROSE_MODEL,
    )


def _render_cv_document(
    offer: Offer, *, track: str | None = None, compact: bool = False
) -> tuple[str, str]:
    return _render_cv_document_impl(offer, _deps(), track=track, compact=compact)


def render_html(offer: Offer, *, track: str | None = None) -> tuple[str, str]:
    return _render_html_impl(offer, _deps(), track=track)


def render_html_compact(offer: Offer, *, track: str | None = None) -> tuple[str, str]:
    return _render_html_compact_impl(offer, _deps(), track=track)


def build_pdf_for_offer(
    offer: Offer, dest_pdf: Path, *, dest_html: Path | None = None
) -> dict[str, Any]:
    import pdfs

    return _build_pdf_for_offer_impl(
        offer,
        dest_pdf,
        _deps(html_to_pdf_fn=pdfs.html_to_pdf),
        dest_html=dest_html,
    )


__all__ = [
    "COMPACT_CSS",
    "CSS",
    "Track",
    "_ALTERNANCE_TOKENS",
    "_GUARDRAIL_FACT_PREFIXES",
    "_MONTHS_SHORT_FR",
    "_UPPER_ACRONYMS",
    "_e",
    "_filter_skill_block_items",
    "_is_alternance_offer",
    "_is_job_offer",
    "_keyword_present",
    "_offer_blob",
    "_offer_owned_keywords",
    "_parse_date_safe",
    "_pretty_skill",
    "_render_cv_document",
    "_render_education",
    "_render_experiences",
    "_render_header",
    "_render_projects",
    "_render_skills_section",
    "_render_v1_facts",
    "_resolve_mobility",
    "_score_tracks_for_preset",
    "_short_url",
    "_tag_relevance",
    "build_pdf_for_offer",
    "detect_track",
    "pdf_page_count",
    "render_html",
    "render_html_compact",
    "select_track_for_cv",
]

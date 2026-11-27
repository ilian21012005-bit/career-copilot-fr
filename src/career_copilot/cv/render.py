"""CV document rendering and guaranteed 1-page A4 PDF build pipeline."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from career_copilot.cv.sections import (
    escape_html,
    offer_owned_keywords,
    render_availability_box,
    render_education,
    render_experiences,
    render_header,
    render_projects,
    render_skills_section,
    render_v1_facts,
)
from career_copilot.cv.styles import COMPACT_CSS, CSS
from career_copilot.cv.tracks import (
    is_alternance_offer,
    is_job_offer,
    offer_blob,
    score_tracks_for_preset,
)


@dataclass(frozen=True)
class CvDeps:
    """Explicit runtime dependencies for CV HTML rendering and PDF compilation."""

    get_profile: Callable[[], Any]
    get_preset: Callable[[str], Any]
    default_start_date: date
    default_end_date: date
    default_weeks: int
    ensure_private_directory: Callable[[Path], Any]
    protect_private_file: Callable[[Path], Any]
    write_private_text: Callable[[Path, str], Any]
    html_to_pdf_fn: Callable[[Path, Path], Any] | None = None
    pdf_page_count_fn: Callable[[Path], int] | None = None
    render_html_fn: Callable[..., tuple[str, str]] | None = None
    render_html_compact_fn: Callable[..., tuple[str, str]] | None = None
    select_track_fn: Callable[[Any], str] | None = None


def _build_body_blocks(
    cfg: Any,
    tr: Any,
    track_key: str,
    blob: str,
    *,
    is_job: bool,
    compact: bool,
) -> list[str]:
    body_blocks: list[str] = []
    if cfg.experiences or cfg.projects:
        if cfg.experiences:
            exp_html = render_experiences(cfg.experiences, track_key, blob, compact=compact)
            if exp_html:
                body_blocks.append(exp_html)
        if cfg.projects:
            proj_html = render_projects(cfg.projects, track_key, blob, compact=compact)
            if proj_html:
                body_blocks.append(proj_html)
    elif cfg.facts:
        facts_html = render_v1_facts(cfg.facts, tr, blob, compact=compact)
        if facts_html:
            body_blocks.append(facts_html)
    elif is_job and cfg.job_profile.get("summary_sentences"):
        sentences = [
            str(s).strip() for s in cfg.job_profile.get("summary_sentences", ()) if str(s).strip()
        ]
        if sentences:
            lis = "\n".join(f"      <li>{escape_html(s)}</li>" for s in sentences)
            body_blocks.append(
                f"    <h2>Réalisations & Compétences clés</h2>\n    <ul>\n{lis}\n    </ul>"
            )
    return body_blocks


def render_cv_document(
    offer: Any,
    deps: CvDeps,
    *,
    track: str | None = None,
    compact: bool = False,
) -> tuple[str, str]:
    """Render the full HTML CV document and return ``(html_doc, track_key)``."""
    cfg = deps.get_profile()
    is_job = is_job_offer(offer, cfg)
    is_alt = not is_job and is_alternance_offer(offer, cfg)

    effective_preset = (
        deps.get_preset("student_job_only")
        if is_job and track is None and cfg.preset_id != "student_job_only"
        else cfg.preset
    )
    fallback_key = score_tracks_for_preset(offer, effective_preset)
    track_key = track if (track and track in effective_preset.cv_tracks) else fallback_key
    tr = effective_preset.cv_tracks[track_key]

    cand_name = str(cfg.candidate.get("name") or "Candidat").strip()
    company = (offer.company or "").strip()
    title_meta = f"CV — {cand_name}" + (f" — {company}" if company else "")
    desc_meta = f"CV {tr.label}" + (f" — {offer.title} — {company}" if company else "")

    owned_kw = offer_owned_keywords(offer, cfg)
    owned_line = (
        f" Mots-clés offre maîtrisés : <strong>{escape_html(' · '.join(owned_kw))}</strong>."
        if owned_kw
        else ""
    )

    body_blocks = _build_body_blocks(
        cfg,
        tr,
        track_key,
        offer_blob(offer),
        is_job=is_job,
        compact=compact,
    )
    style_css = CSS + (COMPACT_CSS if compact else "")
    sections_joined = "\n\n".join(body_blocks)
    if sections_joined:
        sections_joined = "\n\n" + sections_joined

    availability_box = render_availability_box(
        offer,
        cfg,
        tr,
        is_job=is_job,
        is_alt=is_alt,
        default_start_date=deps.default_start_date,
        default_end_date=deps.default_end_date,
        default_weeks=deps.default_weeks,
    )
    doc = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape_html(title_meta)}</title>
  <meta name="description" content="{escape_html(desc_meta)}" />
  <style>
{style_css}
  </style>
</head>
<body>
  <div class="sheet">
{render_header(cfg)}

    <h2>Profil</h2>
    <p class="profil">
      {tr.profile}{owned_line}
    </p>
{availability_box}{sections_joined}

{render_skills_section(cfg, effective_preset, tr, compact=compact)}

{render_education(cfg)}

    <div class="spacer" aria-hidden="true"></div>
  </div>
</body>
</html>
"""
    return doc, track_key


def render_html(offer: Any, deps: CvDeps, *, track: str | None = None) -> tuple[str, str]:
    """Return ``(html, track_key)`` in standard 1-page A4 layout."""
    return render_cv_document(offer, deps, track=track, compact=False)


def render_html_compact(offer: Any, deps: CvDeps, *, track: str | None = None) -> tuple[str, str]:
    """Return ``(html, track_key)`` in compact 1-page A4 fallback layout."""
    return render_cv_document(offer, deps, track=track, compact=True)


def pdf_page_count(pdf: Path) -> int:
    """Return the PDF page count via ``pdfinfo``, or ``0`` if unavailable."""
    pdfinfo_bin = shutil.which("pdfinfo")
    if not pdfinfo_bin:
        return 0
    try:
        out = subprocess.check_output(  # noqa: S603
            [pdfinfo_bin, str(pdf)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in out.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return 0
    return 0


def build_pdf_for_offer(
    offer: Any,
    dest_pdf: Path,
    deps: CvDeps,
    *,
    dest_html: Path | None = None,
) -> dict[str, Any]:
    """Generate personalized HTML + PDF guaranteed to fit on exactly 1 A4 page."""
    if deps.html_to_pdf_fn is None:
        raise RuntimeError("html_to_pdf_fn est requis pour compiler le CV PDF.")

    html_path = dest_html or dest_pdf.with_suffix(".html")
    deps.ensure_private_directory(html_path.parent)
    deps.ensure_private_directory(dest_pdf.parent)

    count_pages = deps.pdf_page_count_fn or pdf_page_count
    render_std = deps.render_html_fn or (lambda o, *, track=None: render_html(o, deps, track=track))
    render_cmp = deps.render_html_compact_fn or (
        lambda o, *, track=None: render_html_compact(o, deps, track=track)
    )
    selected_track = deps.select_track_fn(offer) if deps.select_track_fn else None

    html_doc, track = render_std(offer, track=selected_track)
    deps.write_private_text(html_path, html_doc)
    deps.html_to_pdf_fn(html_path, dest_pdf)
    deps.protect_private_file(dest_pdf)
    pages = count_pages(dest_pdf)
    mode = "standard"

    if pages != 1:
        html_doc, track = render_cmp(offer, track=track)
        deps.write_private_text(html_path, html_doc)
        deps.html_to_pdf_fn(html_path, dest_pdf)
        deps.protect_private_file(dest_pdf)
        pages = count_pages(dest_pdf)
        mode = "compact"

    if pages != 1:
        raise RuntimeError(
            f"CV personnalisé hors format 1 page ({pages} pages) pour "
            f"{getattr(offer, 'id', '?')!r} / {getattr(offer, 'company', '?')!r}"
        )

    return {
        "track": track,
        "html": str(html_path),
        "pdf": str(dest_pdf),
        "pages": pages,
        "mode": mode,
        "bytes": dest_pdf.stat().st_size if dest_pdf.exists() else 0,
    }

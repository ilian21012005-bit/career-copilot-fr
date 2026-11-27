"""Letter persistence, cryptographic validation metadata, and PDF rendering."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_copilot.letters.bodies import job_body, stage_body
from career_copilot.letters.extraction import lines, notes
from career_copilot.letters.fit import compute_offer_fit
from career_copilot.letters.formatting import (
    campaign_of_target,
    candidate_name,
    dateline,
    header_line,
    subject_for,
)
from career_copilot.letters.text_utils import (
    html_document,
    is_alternance_text,
    short_title,
    url_key,
)
from career_copilot.profile import CandidateProfileConfig

LOG = logging.getLogger("offer_letters")
PROFILE_UNREAD = object()


@dataclass(frozen=True)
class LetterDeps:
    """Explicit dependencies for letter persistence, validation, and PDF generation."""

    folder: Callable[[], Path]
    get_profile: Callable[[], CandidateProfileConfig]
    ensure_private_directory: Callable[[Path], Any]
    protect_private_file: Callable[[Path], Any]
    write_private_text: Callable[[Path, str], Any]
    read_offer_page: Callable[[str], str]
    html_to_pdf: Callable[[Path, Path], Any]
    profile_fingerprint: Callable[[], str | None]
    ai_profile: Callable[[], str]
    name_override: Callable[[], str]
    sender_name: Callable[[], str]
    compose_ai_fn: Callable[..., tuple[str, str, str] | None] | None = None
    ensure_pdf_fn: Callable[[str], Path | None] | None = None
    load_fn: Callable[[str], dict[str, Any] | None] | None = None
    validation_is_current_fn: Callable[..., bool] | None = None
    validation_metadata_fn: Callable[..., dict[str, Any]] | None = None


def profile_digest(cfg: CandidateProfileConfig) -> str:
    cand = cfg.candidate
    exp_part = "|".join(f"{e.get('company', '')}:{e.get('role', '')}" for e in cfg.experiences)
    proj_part = "|".join(str(p.get("name") or "") for p in cfg.projects)
    return (
        f"{cfg.preset_id}|{cand.get('level', '')}|{cand.get('school', '')}|{exp_part}|{proj_part}"
    )


def validation_metadata(
    deps: LetterDeps,
    letter: str,
    stage: bool,
    kind: str,
    *,
    profile_source: Any = PROFILE_UNREAD,
) -> dict[str, Any]:
    """Bind validation state to exact letter text and active candidate profile."""
    sources = deps.profile_fingerprint() if profile_source is PROFILE_UNREAD else profile_source
    if not sources:
        raise ValueError("Sources du profil indisponibles")
    cfg = deps.get_profile()
    cand_name = candidate_name(
        cfg, name_override=deps.name_override(), sender_name=deps.sender_name()
    )
    profile_blob = f"v2|{stage}|{cand_name}|{profile_digest(cfg)}|{deps.ai_profile()}|{sources}"
    return {
        "version": 1,
        "kind": kind,
        "letter_sha256": hashlib.sha256(letter.encode("utf-8")).hexdigest(),
        "profile_sha256": hashlib.sha256(profile_blob.encode("utf-8")).hexdigest(),
    }


def validation_is_current(
    deps: LetterDeps,
    data: dict[str, Any],
    *,
    profile_source: Any = PROFILE_UNREAD,
) -> bool:
    """Reject stale, tampered, or unvalidated letter content."""
    try:
        meta = data.get("validation")
        if not isinstance(meta, dict) or meta.get("kind") not in {"ai_checked", "template"}:
            return False
        letter = data.get("letter")
        stage = data.get("stage")
        if not isinstance(letter, str) or not letter.strip() or not isinstance(stage, bool):
            return False
        meta_fn = deps.validation_metadata_fn or (
            lambda txt, stg, knd, *, profile_source=PROFILE_UNREAD: validation_metadata(
                deps, txt, stg, knd, profile_source=profile_source
            )
        )
        return meta == meta_fn(letter, stage, meta["kind"], profile_source=profile_source)
    except (ImportError, ValueError, TypeError, KeyError):
        return False


def compose(
    deps: LetterDeps,
    title: str,
    company: str,
    city: str,
    stage: bool,
    source: str,
    mission_items: list[str] | None = None,
    *,
    campaign: str | None = None,
) -> tuple[str, str, str]:
    resolved = campaign or (
        "job" if not stage else ("alternance" if is_alternance_text(title) else "stage")
    )
    if os.getenv("DISABLE_AI") != "1" and deps.compose_ai_fn is not None:
        ai_res = deps.compose_ai_fn(
            title, company, city, stage, source, mission_items, campaign=resolved
        )
        if ai_res:
            return ai_res

    cfg = deps.get_profile()
    cand_name = candidate_name(
        cfg, name_override=deps.name_override(), sender_name=deps.sender_name()
    )
    lines_list = lines(source)
    note_text = notes(lines_list, mission_items)
    written = dateline(cfg)
    header = header_line(cfg, name_override=deps.name_override(), sender_name=deps.sender_name())
    short = short_title(title)
    clean_city = city.split(",")[0].strip()
    place = f" à {clean_city}" if clean_city else ""
    subject = subject_for(resolved, short, company)
    if resolved in ("stage", "alternance"):
        body = stage_body(
            cfg,
            cand_name,
            company,
            place,
            short,
            lines_list,
            source,
            mission_items,
            campaign=resolved,
        )
    else:
        body = job_body(cfg, cand_name, company, place, short, source)
    letter = f"{header}\n\n{written}\n\nObjet : {subject}\n\n{body}"
    return subject, letter, note_text


def load(deps: LetterDeps, url: str) -> dict[str, Any] | None:
    path = deps.folder() / f"{url_key(url)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_many(deps: LetterDeps, urls: list[str]) -> dict[str, dict[str, Any]]:
    wanted = {url_key(url): url for url in urls if url}
    if not wanted:
        return {}
    try:
        paths = {path.stem: path for path in deps.folder().glob("*.json")}
    except OSError:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, url in wanted.items():
        path = paths.get(key)
        if not path:
            continue
        try:
            result[url] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return result


def ensure_pdf(deps: LetterDeps, url: str) -> Path | None:
    load_fn = deps.load_fn or (lambda u: load(deps, u))
    saved = load_fn(url)
    if not saved or not saved.get("letter"):
        return None
    folder = deps.folder()
    deps.ensure_private_directory(folder)
    key = url_key(url)
    html_path = folder / f"{key}.html"
    pdf_file = folder / f"{key}.pdf"
    source = folder / f"{key}.json"
    if pdf_file.exists() and source.exists() and pdf_file.stat().st_mtime >= source.stat().st_mtime:
        deps.protect_private_file(pdf_file)
        return pdf_file
    deps.write_private_text(html_path, html_document(saved["letter"]))
    deps.html_to_pdf(html_path, pdf_file)
    deps.protect_private_file(pdf_file)
    return pdf_file


def pdf_path(deps: LetterDeps, url: str) -> Path:
    return deps.folder() / f"{url_key(url)}.pdf"


def pdf_name(deps: LetterDeps, url: str) -> str:
    load_fn = deps.load_fn or (lambda u: load(deps, u))
    saved = load_fn(url) or {}
    company = (
        re.sub(r"[^A-Za-z0-9]+", "-", saved.get("company") or "offre").strip("-")[:40] or "offre"
    )
    campaign = str(saved.get("campaign") or "")
    if campaign == "alternance":
        kind = "alternance"
    elif campaign == "stage" or saved.get("stage"):
        kind = "stage"
    else:
        kind = "job"
    return f"Lettre-{company}-{kind}.pdf"


def save(
    deps: LetterDeps,
    target: dict[str, Any],
    page_text: str | None = None,
    mission_items: list[str] | None = None,
) -> Path:
    folder = deps.folder()
    deps.ensure_private_directory(folder)
    url = (target.get("url") or "").strip()
    load_fn = deps.load_fn or (lambda u: load(deps, u))
    valid_fn = deps.validation_is_current_fn or (lambda d: validation_is_current(deps, d))
    existing_ai = load_fn(url) if url else None
    if (
        existing_ai
        and (existing_ai.get("ai") is True or "Généré par IA" in str(existing_ai.get("info") or ""))
        and valid_fn(existing_ai)
        and os.getenv("LM_FORCE", "").strip().lower() not in {"1", "true", "yes"}
    ):
        return folder / f"{url_key(url)}.json"

    title = (target.get("title") or "ce poste").strip()
    company = (target.get("name") or target.get("company") or "votre entreprise").strip()
    city = (target.get("city") or "").strip()
    campaign = campaign_of_target(target, title)
    stage = campaign in ("stage", "alternance")
    page = page_text or deps.read_offer_page(url)
    fallback = target.get("description") or target.get("text") or ""
    source = page if len(page) > len(fallback) else (page or fallback)
    subject, letter, note_text = compose(
        deps, title, company, city, stage, source, mission_items, campaign=campaign
    )
    fit = compute_offer_fit(deps.get_profile(), title, source, stage=stage, campaign=campaign)
    meta_fn = deps.validation_metadata_fn or (
        lambda txt, stg, knd: validation_metadata(deps, txt, stg, knd)
    )
    path = folder / f"{url_key(url)}.json"
    deps.write_private_text(
        path,
        json.dumps(
            {
                "url": url,
                "subject": subject,
                "letter": letter,
                "info": note_text,
                "validation": meta_fn(
                    letter,
                    stage,
                    "ai_checked" if note_text == "Généré par IA" else "template",
                ),
                "company": company,
                "stage": stage,
                "campaign": campaign,
                "fit": fit,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    pdf_fn = deps.ensure_pdf_fn or (lambda u: ensure_pdf(deps, u))
    try:
        pdf_fn(url)
    except (OSError, RuntimeError, ValueError) as exc:
        LOG.debug("ensure_pdf skipped: %s", exc)
    return path

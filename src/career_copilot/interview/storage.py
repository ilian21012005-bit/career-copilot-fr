"""Interview preparation persistence and deterministic generation orchestrator."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_copilot.interview.context import build_context_from_config, build_pitch_2min
from career_copilot.interview.questions_domain import select_technical_questions
from career_copilot.interview.rh_questions import build_recruiter_questions, build_rh_questions


@dataclass(frozen=True)
class InterviewDeps:
    """Explicit runtime dependencies for interview prep generation and persistence."""

    get_profile: Callable[[], Any]
    folder: Callable[[], Path]
    ensure_private_directory: Callable[[Path], Any]
    write_private_text: Callable[[Path, str], Any]
    load_prep_fn: Callable[[str], dict[str, Any] | None] | None = None
    save_prep_fn: Callable[[str, dict[str, Any]], Path] | None = None
    generate_prep_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def prep_key(url: str) -> str:
    """Compute a deterministic 24-hex cache key for an offer URL."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:24]


def load_prep(url: str, folder: Path) -> dict[str, Any] | None:
    """Load a saved interview prep brief from ``folder`` if present and valid JSON."""
    if not url:
        return None
    path = folder / f"{prep_key(url)}.json"
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def save_prep(
    url: str,
    data: dict[str, Any],
    folder: Path,
    *,
    ensure_private_directory: Callable[[Path], Any],
    write_private_text: Callable[[Path, str], Any],
) -> Path:
    """Persist an interview prep brief to disk with private permissions."""
    ensure_private_directory(folder)
    path = folder / f"{prep_key(url)}.json"
    write_private_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path


def get_candidate_context(get_profile_fn: Callable[[], Any]) -> dict[str, Any]:
    """Build dynamic factual candidate context from the active profile loader."""
    return build_context_from_config(get_profile_fn())


def generate_deterministic_prep(
    target: dict[str, Any],
    get_profile_fn: Callable[[], Any],
) -> dict[str, Any]:
    """Generate a personalized deterministic interview brief for ``target``."""
    cfg = get_profile_fn()
    ctx = build_context_from_config(cfg)

    default_title = f"Poste — {cfg.preset.label}"
    title = (target.get("title") or default_title).strip()
    company = (target.get("name") or target.get("company") or "l'entreprise").strip()
    city = (target.get("city") or "").strip()
    notes = str(target.get("description") or target.get("notes") or "")
    campaign = str(target.get("campaign") or target.get("type") or "").strip().lower()
    is_job_offer = campaign == "job"
    t_lower = f"{title} {notes}".lower()

    projets: Sequence[Mapping[str, str]] = ctx["projets_phares"]
    pitch_2min = build_pitch_2min(cfg, ctx, company=company, title=title, is_job_offer=is_job_offer)
    tech_q = select_technical_questions(cfg, projets, t_lower=t_lower, is_job_offer=is_job_offer)
    rh_q = build_rh_questions(
        cfg, ctx, company=company, title=title, city=city, pitch_2min=pitch_2min
    )
    strategic_questions = build_recruiter_questions(
        cfg, ctx, company=company, title=title, is_job_offer=is_job_offer
    )

    return {
        "company": company,
        "title": title,
        "city": city,
        "pitch_2min": pitch_2min,
        "technical_questions": tech_q,
        "rh_questions": rh_q,
        "questions_for_recruiter": strategic_questions,
        "source": "deterministic",
    }


def get_or_create_prep(
    target: dict[str, Any],
    deps: InterviewDeps,
    *,
    force_regenerate: bool = False,
) -> dict[str, Any]:
    """Return a cached interview brief or generate and persist a fresh one locally."""
    url = (target.get("url") or "").strip()
    loader = deps.load_prep_fn or (lambda u: load_prep(u, deps.folder()))
    saver = deps.save_prep_fn or (
        lambda u, d: save_prep(
            u,
            d,
            deps.folder(),
            ensure_private_directory=deps.ensure_private_directory,
            write_private_text=deps.write_private_text,
        )
    )
    generator = deps.generate_prep_fn or (
        lambda t: generate_deterministic_prep(t, deps.get_profile)
    )

    if not force_regenerate:
        cached = loader(url)
        if cached:
            return cached

    prep_data = generator(target)
    if url:
        saver(url, prep_data)
    return prep_data

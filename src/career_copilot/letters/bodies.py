"""Letter body generators and explicit typed render context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from career_copilot.letters.extraction import (
    job_tasks,
    mission_sentence,
    missions,
    objective,
    usable_goal,
)
from career_copilot.letters.fit import stage_profile
from career_copilot.letters.formatting import (
    education_intro,
    format_date_fr,
    job_availability_paragraph,
    mobility_closing,
)
from career_copilot.letters.text_utils import fold, join_fr
from career_copilot.profile import CandidateProfileConfig


@dataclass(frozen=True)
class LetterRenderContext:
    """Explicit typed callbacks passed to AI letter composers."""

    _candidate_name: Callable[[CandidateProfileConfig | None], str]
    _dateline: Callable[[CandidateProfileConfig | None], str]
    _header_line: Callable[[CandidateProfileConfig | None], str]
    _subject_for: Callable[[str, str, str], str]
    _format_date_fr: Callable[[Any], str]
    _job_availability_text: Callable[[CandidateProfileConfig], str]


def stage_body(
    cfg: CandidateProfileConfig,
    cand_name: str,
    company: str,
    place: str,
    short: str,
    lines_list: list[str],
    source: str,
    mission_items: list[str] | None = None,
    *,
    campaign: str = "stage",
) -> str:
    cand = cfg.candidate
    edu_intro = education_intro(cfg)
    start_fr = format_date_fr(cand.get("start"))
    end_fr = format_date_fr(cand.get("end"))
    weeks = cand.get("weeks")

    if campaign == "alternance":
        when_part = f" à compter du {start_fr}" if start_fr else ""
        opening = (
            f"{edu_intro}, je recherche un contrat en alternance{when_part} en lien avec mon cursus. "
            f"Je souhaite rejoindre {company}{place} sur le poste « {short} »."
        )
    else:
        period_bits: list[str] = []
        if start_fr and end_fr:
            period_bits.append(f"du {start_fr} au {end_fr}")
        if weeks:
            period_bits.append(f"d’une durée de {weeks} semaines")
        period_txt = (" " + ", ".join(period_bits) + ",") if period_bits else ""
        opening = (
            f"{edu_intro}, je recherche un stage{period_txt} dans un domaine lié à ma formation. "
            f"Je souhaite le réaliser chez {company}{place}, sur le sujet « {short} »."
        )

    goal = usable_goal(objective(lines_list))
    resolved_missions = mission_items or missions(lines_list)
    profile_para = stage_profile(cfg, source)
    middle = "\n\n".join(
        part for part in (goal, profile_para, mission_sentence(resolved_missions)) if part
    )
    closing = mobility_closing(cfg)
    return (
        "Madame, Monsieur,\n\n"
        f"{opening}\n\n"
        f"{middle}\n\n"
        f"{closing}\n\n"
        "Veuillez agréer, Madame, Monsieur, l’expression de mes salutations distinguées.\n\n"
        f"{cand_name}"
    )


def job_body(
    cfg: CandidateProfileConfig,
    cand_name: str,
    company: str,
    place: str,
    short: str,
    source: str,
) -> str:
    cand = cfg.candidate
    jp = cfg.job_profile or {}
    confirmed_folded = {fold(t) for t in (jp.get("confirmed_tasks") or []) if str(t).strip()}
    if not confirmed_folded:
        evidence_blob = " ".join(
            [
                *cfg.facts,
                *(
                    f"{exp.get('role', '')} {exp.get('company', '')} {' '.join(exp.get('bullets') or ())}"
                    for exp in cfg.experiences
                ),
            ]
        )
        for task in job_tasks(evidence_blob):
            confirmed_folded.add(fold(task))
    retail_ctx = str(jp.get("retail_context") or "en commerce et relation client").strip()
    tasks = job_tasks(source)
    task_sentence = ""
    if tasks:
        known = [task for task in tasks if fold(task) in confirmed_folded]
        to_learn = [task for task in tasks if fold(task) not in confirmed_folded]
        parts: list[str] = []
        if known:
            ctx_suffix = f" {retail_ctx}" if retail_ctx else ""
            parts.append(f"J’ai déjà pratiqué {join_fr(known)}{ctx_suffix}.")
        if to_learn:
            parts.append(
                f"L’annonce porte aussi sur {join_fr(to_learn)}. Mon expérience de la relation client, "
                "du respect des procédures et du travail en équipe est transférable à ces missions."
            )
        task_sentence = " " + " ".join(parts)

    level = str(cand.get("level") or "").strip()
    school = str(cand.get("school") or "").strip()
    if level and school:
        student_intro = f"Étudiant en {level} à {school}"
    elif level:
        student_intro = f"Étudiant en {level}"
    else:
        student_intro = "Étudiant dans l’enseignement supérieur"

    summary_lines = [
        str(sentence).strip()
        for sentence in (jp.get("summary_sentences") or [])
        if str(sentence).strip()
    ]
    experience_para = " ".join(summary_lines) or (
        "Lors de mes expériences en accueil client et commerce, j’ai développé le sens du service, "
        "le respect des procédures et l’esprit d’équipe."
    )
    dispo_para = job_availability_paragraph(cfg)

    return (
        "Madame, Monsieur,\n\n"
        f"{student_intro}, je recherche un emploi étudiant et je vous propose "
        f"ma candidature pour le poste « {short} » chez {company}{place}.{task_sentence}\n\n"
        f"{experience_para}\n\n"
        f"{dispo_para}\n\n"
        "Veuillez agréer, Madame, Monsieur, l’expression de mes salutations distinguées.\n\n"
        f"{cand_name}"
    )

"""Courriers génériques et relances pilotés par le profil candidat (avec lecture Markdown si disponible)."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import candidate_config
from config import LETTER, ROOT, SENDER_NAME

_MONTHS = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _sender_name(cfg: candidate_config.CandidateProfileConfig) -> str:
    name = str(cfg.candidate.get("name") or "").strip()
    if name:
        return name
    env_sender = os.getenv("SENDER_NAME", "").strip()
    if env_sender:
        return env_sender
    sender = str(SENDER_NAME or "").strip()
    if sender and sender.lower() != "candidat":
        return sender
    return "Le candidat"


def _format_date_fr(raw_date: Any) -> str:
    parsed: date | None = None
    if isinstance(raw_date, date):
        parsed = raw_date
    elif isinstance(raw_date, str) and raw_date.strip():
        try:
            parsed = date.fromisoformat(raw_date.strip()[:10])
        except ValueError:
            return ""
    if parsed is None:
        return ""
    day_txt = "1er" if parsed.day == 1 else str(parsed.day)
    return f"{day_txt} {_MONTHS[parsed.month - 1]} {parsed.year}"


def _period_label(cfg: candidate_config.CandidateProfileConfig) -> str:
    start_fr = _format_date_fr(cfg.candidate.get("start"))
    end_fr = _format_date_fr(cfg.candidate.get("end"))
    if start_fr and end_fr:
        return f"{start_fr} au {end_fr}"
    return ""


def _should_use_markdown_file(path_key: str) -> bool:
    path = LETTER.get(path_key)
    if path is None or not path.is_file():
        return False
    if path_key == "alternance" and LETTER.get("alternance") == LETTER.get("stage"):
        return False
    custom_env = os.getenv(candidate_config.PROFILE_PATH_ENV, "").strip()
    if custom_env:
        custom_target = candidate_config.profile_path().resolve()
        default_target = candidate_config.DEFAULT_PROFILE_PATH.resolve()
        if custom_target != default_target:
            try:
                path.resolve().relative_to(ROOT.resolve())
            except ValueError:
                return True
            return False
    return not candidate_config.is_standalone_mode()


def _plain_from_disk(path_key: str) -> str | None:
    if not _should_use_markdown_file(path_key):
        return None
    path = LETTER.get(path_key)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if path_key == "job":
        text = text.split("## Version ultra-courte")[0]
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "---")):
            continue
        lines.append(line.replace("**", ""))
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def _profile_highlights_paragraph(cfg: candidate_config.CandidateProfileConfig) -> str:
    parts: list[str] = []
    if cfg.experiences or cfg.projects:
        for exp in cfg.experiences[:2]:
            role = str(exp.get("role") or "").strip()
            comp = str(exp.get("company") or "").strip()
            bullets = [
                str(b).strip().rstrip(".")
                for b in (exp.get("bullets") or [])
                if str(b).strip()
            ]
            head = (
                f"En tant que {role} chez {comp}"
                if role and comp
                else f"Chez {comp}"
                if comp
                else f"En tant que {role}"
                if role
                else "En expérience terrain"
            )
            if bullets:
                parts.append(
                    f"{head}, j’ai notamment mené : {' ; '.join(bullets[:2])}."
                )
        for proj in cfg.projects[:2]:
            p_name = str(proj.get("name") or "").strip()
            p_sum = str(proj.get("summary") or "").strip().rstrip(".")
            if p_name and p_sum:
                parts.append(f"J’ai également réalisé le projet {p_name} ({p_sum}).")
    elif cfg.facts:
        for raw_fact in cfg.facts[:3]:
            fact = str(raw_fact).strip()
            if fact:
                parts.append(fact if fact.endswith((".", "!", "?")) else f"{fact}.")
    if not parts:
        core = [s for s in cfg.preset.core_skills if s in cfg.owned_skills][:5]
        skills_str = f" ({', '.join(core)})" if core else ""
        parts.append(
            f"Ma formation orientée {cfg.preset.label} m’a permis de développer des bases solides{skills_str} "
            "et une méthode de travail rigoureuse."
        )
    return " ".join(parts)


def _generated_stage_or_alternance_body(
    company: str,
    cfg: candidate_config.CandidateProfileConfig,
    *,
    alternance: bool,
) -> str:
    cand = cfg.candidate
    sender = _sender_name(cfg)
    level = str(cand.get("level") or "").strip()
    track = str(cand.get("track") or cfg.preset.label or "").strip()
    school = str(cand.get("school") or "").strip()
    edu_bits = [
        part for part in (level, f"({track})" if level and track else track) if part
    ]
    edu_txt = " ".join(edu_bits) or "formation supérieure"
    school_txt = f" à {school}" if school else ""

    period = _period_label(cfg)
    weeks = cand.get("weeks")
    if alternance:
        start_fr = _format_date_fr(cand.get("start"))
        when_txt = f" à partir du {start_fr}" if start_fr else ""
        intro = (
            f"Actuellement en {edu_txt}{school_txt}, je recherche un contrat en alternance{when_txt} "
            f"au sein de {company}, dans le domaine {cfg.preset.label}."
        )
    else:
        period_clause = f" du {period}" if period else ""
        weeks_clause = f" ({weeks} semaines)" if weeks else ""
        intro = (
            f"Actuellement en {edu_txt}{school_txt}, je vous adresse ma candidature pour un stage"
            f"{period_clause}{weeks_clause} chez {company}."
        )

    highlights = _profile_highlights_paragraph(cfg)
    mobility = str(cand.get("mobility") or "").strip()
    if not mobility and cfg.configured and cfg.zones:
        mobility = ", ".join(
            str(z.get("name") or "") for z in cfg.zones if z.get("name")
        )
    mob_sentence = f"Mobile sur {mobility}, je reste " if mobility else "Je reste "
    closing = f"{mob_sentence}à votre disposition pour échanger lors d’un entretien."

    return (
        f"Madame, Monsieur,\n\n"
        f"{intro}\n\n"
        f"{highlights}\n\n"
        f"{closing}\n\n"
        f"Veuillez agréer, Madame, Monsieur, l’expression de mes salutations distinguées.\n\n"
        f"{sender}"
    )


def _generated_job_body(
    company: str, cfg: candidate_config.CandidateProfileConfig
) -> str:
    cand = cfg.candidate
    sender = _sender_name(cfg)
    jp = cfg.job_profile or {}
    level = str(cand.get("level") or "").strip()
    school = str(cand.get("school") or "").strip()
    edu_prefix = (
        f"Étudiant en {level} à {school}"
        if level and school
        else f"Étudiant en {level}"
        if level
        else "Étudiant dans l’enseignement supérieur"
    )
    summary_lines = [
        str(s).strip() for s in (jp.get("summary_sentences") or []) if str(s).strip()
    ]
    experience_para = " ".join(summary_lines) or (
        "Lors de mes expériences en accueil client et commerce, j’ai acquis le sens du service, "
        "la rigueur opérationnelle et l’esprit d’équipe."
    )
    jfa = cfg.job_form_answers or {}
    custom_dispo = ""
    for key in ("disponibilité", "Disponibilité", "disponibilite", "Disponibilite"):
        if str(jfa.get(key) or "").strip():
            custom_dispo = str(jfa[key]).strip().rstrip(".")
            break
    dispo_extra = f" ({custom_dispo})" if custom_dispo else ""
    availability = (
        f"Je suis disponible dès maintenant à temps partiel, notamment les soirs et week-ends{dispo_extra}, "
        "ainsi que pendant les vacances scolaires. Motivé et ponctuel, je reste disponible pour un entretien."
    )
    return (
        f"Madame, Monsieur,\n\n"
        f"{edu_prefix}, je vous propose ma candidature pour un poste d’employé polyvalent au sein de {company}.\n\n"
        f"{experience_para}\n\n"
        f"{availability}\n\n"
        f"Veuillez agréer, Madame, Monsieur, l’expression de mes salutations distinguées.\n\n"
        f"{sender}"
    )


def stage_message(company: str) -> tuple[str, str]:
    cfg = candidate_config.get_profile()
    disk_body = _plain_from_disk("stage")
    if disk_body is not None:
        body = disk_body.replace("[Nom de l’entreprise]", company).replace(
            "[Nom de l'entreprise]", company
        )
    else:
        body = _generated_stage_or_alternance_body(company, cfg, alternance=False)

    level = str(cfg.candidate.get("level") or "").strip()
    track = str(cfg.candidate.get("track") or cfg.preset.label or "stage").strip()
    period = _period_label(cfg)
    head = (
        f"Candidature stage {level} ({track})".strip()
        if level
        else f"Candidature stage — {track}"
    )
    subject = f"{head} — {company}" + (f" — {period}" if period else "")
    return subject, body


def alternance_message(company: str) -> tuple[str, str]:
    cfg = candidate_config.get_profile()
    disk_body = _plain_from_disk("alternance")
    if disk_body is not None:
        body = disk_body.replace("[Nom de l’entreprise]", company).replace(
            "[Nom de l'entreprise]", company
        )
    else:
        body = _generated_stage_or_alternance_body(company, cfg, alternance=True)

    level = str(cfg.candidate.get("level") or "").strip()
    track = str(cfg.candidate.get("track") or cfg.preset.label or "alternance").strip()
    head = (
        f"Candidature en alternance {level} ({track})".strip()
        if level
        else f"Candidature en alternance — {track}"
    )
    subject = f"{head} — {company}"
    return subject, body


def job_message(company: str) -> tuple[str, str]:
    cfg = candidate_config.get_profile()
    disk_body = _plain_from_disk("job")
    if disk_body is not None:
        body = (
            disk_body.replace("[Poste / Employé polyvalent]", "employé polyvalent")
            .replace("[Nom de l’enseigne / magasin]", company)
            .replace("[Nom de l'enseigne / magasin]", company)
        )
    else:
        body = _generated_job_body(company, cfg)
    subject = (
        f"Candidature job étudiant — {company} — disponible temps partiel / week-end"
    )
    return subject, body


def message_for(campaign: str, company: str) -> tuple[str, str]:
    normalized = str(campaign or "").strip().lower()
    if normalized == "stage":
        return stage_message(company)
    if normalized == "alternance":
        return alternance_message(company)
    return job_message(company)


def relance(company: str, campaign: str) -> tuple[str, str]:
    cfg = candidate_config.get_profile()
    sender = _sender_name(cfg)
    normalized = str(campaign or "").strip().lower()
    level = str(cfg.candidate.get("level") or "").strip()
    domain = str(cfg.candidate.get("track") or cfg.preset.label or "").strip()
    level_part = f" ({level})" if level else ""

    if normalized == "alternance":
        subject = f"Relance — candidature en alternance{level_part} — {company}"
        body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de relancer ma candidature pour un contrat en alternance "
            f"dans le domaine {domain} chez {company}. "
            f"Mon CV est de nouveau joint.\n\n"
            f"Cordialement,\n{sender}"
        )
    elif normalized == "stage":
        period = _period_label(cfg)
        period_clause = f", du {period}" if period else ""
        subject = f"Relance — candidature stage{level_part} — {company}"
        body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de relancer ma candidature pour un stage "
            f"dans le domaine {domain} chez {company}{period_clause}. "
            f"Mon CV est de nouveau joint.\n\n"
            f"Cordialement,\n{sender}"
        )
    else:
        subject = f"Relance — job étudiant — {company}"
        body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de relancer ma candidature pour un job étudiant chez {company}. "
            f"Je suis disponible dès maintenant à temps partiel (week-ends et soirs) "
            f"ainsi que pendant les vacances scolaires.\n\n"
            f"Cordialement,\n{sender}"
        )
    return subject, body

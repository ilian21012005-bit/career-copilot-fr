"""Dossier de candidature : lettre personnalisée, CV, réponses, checklist.

Le dossier est préparé hors ligne à partir de la fiche déjà lue. Il ne
déclenche aucune candidature : l'envoi reste un geste de l'utilisateur, sur
le site, avec les documents prêts.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import candidate_config
import offer_letters
import pdfs
from config import DATA_DIR
from private_storage import (
    copy_private_file,
    ensure_private_directory,
    write_private_text,
)

from . import profile, store
from . import score as scoring
from .offer import Offer

KITS_DIR = DATA_DIR / "hellowork" / "kits"

_MONTHS_FR = (
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


def build(offer: Offer, score: scoring.Score | None = None) -> dict:
    """Crée le dossier d'une offre et renvoie le récapitulatif des chemins."""
    previous = store.kit_for(offer.id)
    letter_meta = offer_letters.load(offer.url) or {}
    ai_letter = letter_meta.get("ai") is True or "Généré par IA" in str(
        letter_meta.get("info") or ""
    )
    if (
        previous
        and not store.kit_is_current(offer.id, previous)
        and ai_letter
        and letter_meta.get("offer_fingerprint")
        != store.offer_fingerprint(offer.to_dict())
    ):
        raise ValueError(
            "Lettre IA périmée : régénérer et relire la lettre pour l'offre modifiée"
        )
    score = score or scoring.evaluate(offer)
    folder = KITS_DIR / offer.id
    ensure_private_directory(folder)

    subject, letter = _letter(offer)
    letter_pdf = _copy_letter(offer, folder, subject, letter)
    cv_pdf = _copy_cv(folder, offer)
    answers = _answers_path(offer, folder, score)
    checklist = _checklist_path(offer, folder, score, letter_pdf, cv_pdf)

    dossier = {
        "offer": offer.to_dict(),
        "score": {
            "value": score.value,
            "parts": score.parts,
            "reasons": score.reasons,
            "gaps": score.gaps,
            "verdict": score.verdict,
        },
        "subject": subject,
        "letter_text_sha256": hashlib.sha256(letter.encode("utf-8")).hexdigest(),
        "files": {
            "letter": str(letter_pdf) if letter_pdf else "",
            "cv": str(cv_pdf) if cv_pdf else "",
            "answers": str(answers),
            "checklist": str(checklist),
        },
        "prepared_at": date.today().isoformat(),
        "submitted": False,
    }
    dossier_path = folder / "dossier.json"
    write_private_text(dossier_path, json.dumps(dossier, ensure_ascii=False, indent=2))
    return {
        "folder": folder,
        "subject": subject,
        "letter": letter_pdf,
        "cv": cv_pdf,
        "answers": answers,
        "checklist": checklist,
        "dossier": dossier_path,
    }


def _letter(offer: Offer) -> tuple[str, str]:
    campaign = scoring.campaign_of(offer)
    if campaign == "stage":
        default_subject = f"Candidature au stage – {offer.title} – {offer.company}"
    elif campaign == "alternance":
        default_subject = f"Candidature en alternance – {offer.title} – {offer.company}"
    else:
        default_subject = f"Candidature – {offer.title} – {offer.company}"
    target = {
        "url": offer.url,
        "title": offer.title,
        "name": offer.company,
        "city": offer.city,
        "campaign": campaign,
        "description": offer.description,
    }
    offer_letters.save(
        target, page_text=offer.description, missions=_clean_missions(offer)
    )
    saved = offer_letters.load(offer.url) or {}
    subject = str(saved.get("subject") or default_subject)
    letter = str(saved.get("letter") or "")
    return subject, letter


TASK_STARTS = (
    "analyser",
    "auditer",
    "administrer",
    "automatiser",
    "assurer",
    "accompagner",
    "concevoir",
    "configurer",
    "contribuer",
    "deployer",
    "déployer",
    "documenter",
    "developper",
    "développer",
    "effectuer",
    "etudier",
    "étudier",
    "evaluer",
    "évaluer",
    "exploiter",
    "generer",
    "générer",
    "implementer",
    "implémenter",
    "installer",
    "integrer",
    "intégrer",
    "maintenir",
    "mesurer",
    "mettre en place",
    "mettre en oeuvre",
    "mettre en œuvre",
    "modeliser",
    "modéliser",
    "optimiser",
    "participer",
    "realiser",
    "réaliser",
    "rediger",
    "rédiger",
    "superviser",
    "surveiller",
    "tester",
    "traiter",
    "verifier",
    "vérifier",
)


def _clean_missions(offer: Offer) -> list[str]:
    """Extrait les tâches concrètes de l'annonce, pour une lettre précise."""
    found: list[str] = []
    for raw in (offer.missions or "").splitlines():
        line = " ".join(raw.split()).strip(" -–—•")
        folded = line.lower()
        if not (18 <= len(line) <= 150):
            continue
        if "?" in line or "!" in line:
            continue
        if not folded.startswith(TASK_STARTS):
            continue
        short = _trim_task(line)
        if short and short not in found:
            found.append(short[0].lower() + short[1:])
        if len(found) == 3:
            break
    return found


DANGLING = (
    "et",
    "ou",
    "de",
    "des",
    "du",
    "la",
    "le",
    "les",
    "l'",
    "d'",
    "à",
    "a",
    "dans",
    "sur",
    "pour",
    "avec",
    "en",
    "un",
    "une",
    "au",
    "aux",
    "par",
)


def _trim_task(line: str, limit: int = 96) -> str:
    """Coupe une tâche à une frontière lisible, sans mot outil orphelin."""
    text = line if len(line) <= limit else line[:limit]
    if len(text) < len(line):
        text = text.rsplit(" ", 1)[0]
        for separator in (", ", "; ", " : "):
            index = text.rfind(separator)
            if index >= 55:
                text = text[:index]
                break
    words = text.split()
    while words and words[-1].lower().strip(".,;:") in DANGLING:
        words.pop()
    return " ".join(words).rstrip(".,;:")


def _copy_letter(offer: Offer, folder: Path, subject: str, letter: str) -> Path | None:
    try:
        source = offer_letters.ensure_pdf(offer.url)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        source = None
    name = f"Lettre-{_slug(offer.company)}.pdf"
    destination = folder / name
    if source and Path(source).exists():
        copy_private_file(Path(source), destination)
        return destination
    text = folder / "lettre.txt"
    write_private_text(text, f"Objet : {subject}\n\n{letter}\n")
    return text


def _copy_cv(folder: Path, offer: Offer) -> Path | None:
    campaign = scoring.campaign_of(offer)
    if campaign in ("stage", "alternance"):
        try:
            from . import cv_personalize

            cv_prefix = profile.candidate_cv_prefix()
            tag = "Alternance" if campaign == "alternance" else "Stage"
            destination = folder / f"{cv_prefix}-{tag}-Personnalise.pdf"
            html_path = folder / f"{cv_prefix}-{tag}-Personnalise.html"
            cv_personalize.build_pdf_for_offer(offer, destination, dest_html=html_path)
            if destination.exists() and destination.stat().st_size > 1000:
                return destination
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            pass
    try:
        ensured = pdfs.ensure_pdfs()
        pdf = ensured.get(campaign) or ensured.get("stage")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        return None
    suffix = (
        "Job-Etudiant"
        if campaign == "job"
        else ("Alternance" if campaign == "alternance" else "Stage")
    )
    name = f"{profile.candidate_cv_prefix()}-{suffix}.pdf"
    destination = folder / name
    if pdf and Path(pdf).exists():
        copy_private_file(Path(pdf), destination)
        return destination
    return None


def _answers_path(offer: Offer, folder: Path, score: scoring.Score) -> Path:
    path = folder / "reponses.md"
    write_private_text(path, _answers(offer, score))
    return path


def _checklist_path(
    offer: Offer,
    folder: Path,
    score: scoring.Score,
    letter: Path | None,
    cv: Path | None,
) -> Path:
    path = folder / "checklist.md"
    write_private_text(path, _checklist(offer, score, letter, cv))
    return path


def _parse_date(raw: Any, fallback: date) -> date:
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and len(raw.strip()) >= 10:
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return fallback
    return fallback


def _join_fr(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " et " + items[-1]


def _format_period_fr(start: date, end: date) -> str:
    if start.year == end.year:
        return (
            f"{start.day} {_MONTHS_FR[start.month - 1]} "
            f"au {end.day} {_MONTHS_FR[end.month - 1]} {end.year}"
        )
    return (
        f"{start.day} {_MONTHS_FR[start.month - 1]} {start.year} "
        f"au {end.day} {_MONTHS_FR[end.month - 1]} {end.year}"
    )


def _format_education(cfg: candidate_config.CandidateProfileConfig) -> str:
    cand = cfg.candidate
    parts = [
        str(cand.get(key) or "").strip()
        for key in ("level", "track", "school")
        if str(cand.get(key) or "").strip()
    ]
    return (
        ", ".join(parts) + "." if parts else f"Formation orientée {cfg.preset.label}."
    )


def _format_mobility(
    cfg: candidate_config.CandidateProfileConfig, *, is_job: bool
) -> str:
    if is_job:
        custom_job = str(
            cfg.job_form_answers.get("Mobilité")
            or cfg.job_form_answers.get("mobilité")
            or ""
        ).strip()
        if custom_job:
            return custom_job
        city = str(
            cfg.candidate.get("home") or (cfg.zones[0]["name"] if cfg.zones else "")
        ).strip()
        km = f"{float(cfg.job_radius_km):g} km"
        return (
            f"{city} et environs dans un rayon de {km}."
            if city
            else f"Dans un rayon de {km} autour du domicile."
        )

    zone_names = [str(z.get("name") or "").strip() for z in cfg.zones if z.get("name")]
    max_km = f"{max((float(z.get('km', 30.0)) for z in cfg.zones), default=30.0):g} km"
    custom = str(
        cfg.candidate.get("mobility") or cfg.form_answers.get("Mobilité") or ""
    ).strip()
    if zone_names:
        base = (
            f"{_join_fr(zone_names)}, dans un rayon de {max_km} autour de chaque zone."
        )
        if custom and custom.lower() not in base.lower():
            return f"{base} ({custom})"
        return base
    return custom or "Selon les zones configurées dans le profil candidat."


def _format_experience_bullets(
    cfg: candidate_config.CandidateProfileConfig, *, is_job: bool
) -> str:
    lines: list[str] = []
    for exp in cfg.experiences:
        role = str(exp.get("role") or "").strip()
        company = str(exp.get("company") or "").strip()
        dates = str(exp.get("dates") or "").strip()
        bullets = [str(b).strip() for b in (exp.get("bullets") or ()) if str(b).strip()]
        head = " chez ".join(p for p in (role, company) if p) or "Expérience"
        if dates:
            head += f" ({dates})"
        detail = f" : {'; '.join(bullets[:3])}" if bullets else ""
        lines.append(f"- {head}{detail}")

    if is_job:
        for sentence in cfg.job_profile.get("summary_sentences", ()):
            clean_s = str(sentence).strip()
            if clean_s:
                lines.append(f"- {clean_s}")
        if not cfg.experiences:
            for fact in cfg.facts[:4]:
                lines.append(f"- {fact}")
        lines.append(f"- Formation : {_format_education(cfg)}")
        return "\n".join(lines)

    for proj in cfg.projects:
        name = str(proj.get("name") or "").strip()
        summary = str(proj.get("summary") or "").strip()
        if name or summary:
            label = (
                f"Projet {name} : {summary}"
                if (name and summary)
                else (name or summary)
            )
            lines.append(f"- {label}")

    for fact in cfg.facts:
        clean_f = str(fact).strip()
        if clean_f and f"- {clean_f}" not in lines:
            lines.append(f"- {clean_f}")

    if not lines:
        lines.append(
            "- À compléter dans votre profil candidat (expériences, projets et réalisations vérifiées)."
        )
    return "\n".join(lines)


def _answers_job(
    offer: Offer,
    score: scoring.Score,
    cfg: candidate_config.CandidateProfileConfig,
) -> str:
    default_tasks = ", ".join(cfg.job_profile.get("confirmed_tasks", ())[:4])
    skills = (
        ", ".join(score.matched[:6])
        or default_tasks
        or "accueil client, rigueur, polyvalence"
    )
    dispo = str(
        cfg.job_form_answers.get("Disponibilité")
        or cfg.job_form_answers.get("disponibilité")
        or "Disponible à temps partiel (soirs, week-ends) et pendant les vacances scolaires, compatible avec le planning d'études."
    ).strip()
    mobility = _format_mobility(cfg, is_job=True)
    experiences = _format_experience_bullets(cfg, is_job=True)
    return f"""# Réponses prêtes (Job étudiant) — {offer.company}

Annonce : {offer.title} — {offer.location}
Lien : {offer.url}

## Disponibilité & contrat
{dispo}

## Mobilité
{mobility}

## Expériences vérifiées
{experiences}

## Points à mettre en avant
{skills}
"""


def _answers_stage_or_alternance(
    offer: Offer,
    score: scoring.Score,
    cfg: candidate_config.CandidateProfileConfig,
    *,
    is_alternance: bool,
) -> str:
    start = _parse_date(cfg.candidate.get("start"), candidate_config.DEFAULT_START_DATE)
    end = _parse_date(cfg.candidate.get("end"), candidate_config.DEFAULT_END_DATE)
    weeks = int(cfg.candidate.get("weeks") or candidate_config.DEFAULT_WEEKS)
    zone_names = [str(z.get("name") or "").strip() for z in cfg.zones if z.get("name")]
    zones_text = _join_fr(zone_names) or "les zones configurées"
    custom_dispo = str(
        cfg.form_answers.get("Disponibilité")
        or cfg.form_answers.get("disponibilité")
        or ""
    ).strip()

    if is_alternance:
        header_tag = " (Alternance)"
        start_label = f"{start.day} {_MONTHS_FR[start.month - 1]} {start.year}"
        dates_line = (
            custom_dispo
            or f"Alternance (apprentissage ou professionnalisation) disponible à partir du {start_label}."
        )
        pretentions = "Alternance : rémunération légale selon l'âge et l'année d'études (ou grille conventionnelle)."
    else:
        header_tag = ""
        period = _format_period_fr(start, end)
        dates_line = f"Stage du {period} ({weeks} semaines), temps plein."
        pretentions = "Stage : gratification légale en vigueur, à confirmer selon la grille de l'entreprise."

    dispo_prefix = (
        f"{custom_dispo} "
        if (custom_dispo and not is_alternance)
        else "Disponible sur toute la période. "
    )
    dispo_line = f"{dispo_prefix}Entretien possible en visioconférence ou sur place ({zones_text})."
    mobility = _format_mobility(cfg, is_job=False)
    education = _format_education(cfg)
    experiences = _format_experience_bullets(cfg, is_job=False)
    default_skills = (
        ", ".join(sorted(cfg.owned_skills)[:4])
        or ", ".join(cfg.preset.core_skills[:4])
        or "compétences du profil"
    )
    gap_set = {g.lower() for g in score.gaps}
    owned_matched = [m for m in score.matched if m.lower() not in gap_set]
    skills = ", ".join(owned_matched[:6]) or default_skills
    gaps = ", ".join(score.gaps[:5]) or "aucune"

    return f"""# Réponses prêtes{header_tag} — {offer.company}

Annonce : {offer.title} — {offer.location}
Lien : {offer.url}

## Dates
{dates_line}

## Disponibilité
{dispo_line}

## Mobilité
{mobility}

## Formation
{education}

## Expérience à citer
{experiences}

## Compétences à mettre en avant pour cette annonce
{skills}

## Points à ne pas prétendre
{gaps}

## Pourquoi cette entreprise
À compléter en une phrase après avoir lu la page entreprise : un produit, une
équipe ou un projet précis qui vous parle. Ne pas inventer.

## Prétentions
{pretentions}
"""


def _answers(offer: Offer, score: scoring.Score) -> str:
    cfg = candidate_config.get_profile()
    campaign = scoring.campaign_of(offer)
    if campaign == "job":
        return _answers_job(offer, score, cfg)
    return _answers_stage_or_alternance(
        offer, score, cfg, is_alternance=(campaign == "alternance")
    )


def _checklist(
    offer: Offer, score: scoring.Score, letter: Path | None, cv: Path | None
) -> str:
    letter_name = letter.name if letter else "lettre.txt"
    cv_name = cv.name if cv else "(CV non généré — lancer `python main.py --dry-run`)"
    cv_warning = (
        "\n- [ ] CV personnalisé indisponible : relancer la génération et vérifier le PDF avant tout dépôt."
        if scoring.campaign_of(offer) in ("stage", "alternance")
        and (not cv or "Stage-Personnalise" not in cv_name)
        else ""
    )
    return f"""# Checklist — {offer.company}

Offre : {offer.title}
Lieu : {offer.location}
Score : {score.value}/100 ({score.verdict})
Lien : {offer.url}

- [ ] Ouvrir le lien et relire l'annonce (2 min)
- [ ] Repères du score : {", ".join(score.reasons) or "aucun"}
- [ ] À ne pas prétendre : {", ".join(score.gaps) or "rien de signalé"}
- [ ] Déposer le CV : `{cv_name}`
{cv_warning}
- [ ] Déposer la lettre : `{letter_name}` — objet : {offer.title}
- [ ] Répondre aux questions avec `reponses.md`
- [ ] Vérifier le dossier ; envoi automatique : `python -m hellowork apply {offer.id} --send`

Le bot n'invente pas de réponse aux questions obligatoires. Les offres qui
redirigent vers un ATS externe sont laissées sans action.
"""


def _slug(text: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in (text or "entreprise"))
    return "-".join(part for part in safe.split("-") if part)[:40] or "entreprise"

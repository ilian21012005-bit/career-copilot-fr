"""HR/behavioral questions and strategic questions to ask the recruiter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from career_copilot.interview.context import project_label

_PRIORITIES_BY_PRESET: Mapping[str, str] = {
    "it_infra_cyber": (
        "Quels sont les chantiers prioritaires de l'équipe cette année "
        "(durcissement, supervision, automatisation, conformité) ?"
    ),
    "software_data": (
        "Quels sont les défis techniques ou data prioritaires sur la feuille de route "
        "de l'équipe au cours des prochains mois ?"
    ),
    "engineering_industry": (
        "Quels sont les principaux jalons techniques, essais ou objectifs qualité "
        "prévus sur ce périmètre dans les prochains mois ?"
    ),
    "business_marketing": (
        "Quels sont les objectifs prioritaires et les KPI phares suivis par l'équipe "
        "sur ce trimestre ?"
    ),
    "student_job_only": (
        "Comment s'organisent l'intégration sur le poste et la planification des créneaux "
        "lors des périodes de forte activité ?"
    ),
}


def build_rh_questions(
    cfg: Any,
    ctx: Mapping[str, Any],
    *,
    company: str,
    title: str,
    city: str,
    pitch_2min: str,
) -> list[dict[str, str]]:
    """Build 5 behavioral/HR questions tailored to candidate context and target offer."""
    projets: Sequence[Mapping[str, str]] = ctx.get("projets_phares") or ()
    formation = str(ctx.get("formation") or cfg.preset.label)
    p0_nom = project_label(projets, 0)
    p0_faits = str(projets[0].get("faits") or "") if projets else ""
    location_clause = (
        f" De plus, la localisation à {city} me permet une organisation fiable et ponctuelle."
        if city
        else ""
    )

    return [
        {
            "question": "Présentez-vous en 2 minutes.",
            "answer": pitch_2min,
            "key_project": f"Parcours — {formation}",
            "pitfall": "Réciter son CV de manière chronologique et monotone sans relier ses expériences au poste visé.",
        },
        {
            "question": f"Pourquoi postulez-vous spécifiquement chez {company} ?",
            "answer": (
                f"Ce qui m'attire chez {company}, c'est la cohérence directe entre les enjeux du poste « {title} » "
                f"et ma spécialisation ({cfg.preset.label}). Je souhaite m'investir sur des cas concrets à impact réel "
                f"au sein d'une équipe exigeante.{location_clause}"
            ),
            "key_project": f"Adéquation au poste chez {company}",
            "pitfall": "Donner une réponse générique qui pourrait s'appliquer à n'importe quelle entreprise sans préparation.",
        },
        {
            "question": "Comment gérez-vous une situation où vous êtes confronté à un outil ou un sujet nouveau ?",
            "answer": (
                "J'adopte une autonomie structurée : lecture attentive de la documentation de référence, "
                "mise à l'épreuve rapide sur un cas isolé pour vérifier ma compréhension, puis point synthétique "
                "avec mon tuteur ou responsable en présentant les pistes déjà testées si un blocage subsiste."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Solliciter l'équipe sans aucune recherche préalable ou, à l'inverse, rester bloqué seul trop longtemps.",
        },
        {
            "question": "Parlez-moi d'une expérience où votre rigueur a fait la différence.",
            "answer": (
                f"Dans le cadre de « {p0_nom} » ({p0_faits}), j'ai mis en place des vérifications systématiques "
                "et une traçabilité claire à chaque étape. Cette méthode m'a permis d'éviter les oublis, "
                "de sécuriser la qualité du livrable et de faciliter la relecture par l'équipe."
            ),
            "key_project": p0_nom,
            "pitfall": "Prétendre ne jamais commettre d'erreur au lieu de valoriser ses méthodes de contrôle et de vérification.",
        },
        {
            "question": "Quelle valeur ajoutée concrète pensez-vous apporter à l'équipe dès les premières semaines ?",
            "answer": (
                f"Mon parcours ({formation}) est tourné vers la mise en pratique opérationnelle : "
                "je prends des notes structurées, je respecte les standards de l'équipe, je documente ce que je produis "
                "et je monte rapidement en autonomie sur les tâches récurrentes comme sur les sujets de fond."
            ),
            "key_project": f"Opérationnalité — {formation}",
            "pitfall": "Survendre une expertise senior au lieu de mettre en avant sa fiabilité, sa méthode et sa vitesse d'apprentissage.",
        },
    ]


def build_recruiter_questions(
    cfg: Any,
    ctx: Mapping[str, Any],
    *,
    company: str,
    title: str,
    is_job_offer: bool,
) -> list[str]:
    """Build 3 strategic closing questions to ask the interviewer."""
    second_q = _PRIORITIES_BY_PRESET.get(
        "student_job_only" if is_job_offer else cfg.preset_id,
        _PRIORITIES_BY_PRESET["it_infra_cyber"],
    )
    if is_job_offer or cfg.preset_id == "student_job_only":
        third_q = (
            "Après les premières semaines en poste, quels repères concrets montrent "
            "qu'un équipier donne pleinement satisfaction à l'équipe ?"
        )
    else:
        third_q = (
            f"Au terme de la période ({ctx['dates_stage']}), quels résultats concrets feront "
            "que vous considérerez cette mission comme une pleine réussite pour l'équipe ?"
        )
    return [
        f"Quelle est l'organisation de l'équipe chez {company}, et comment s'articule l'accompagnement au quotidien sur « {title} » ?",
        second_q,
        third_q,
    ]

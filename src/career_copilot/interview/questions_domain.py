"""Business/marketing, student-job question banks, and domain selector."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from career_copilot.interview.context import project_label
from career_copilot.interview.questions_tech import (
    questions_engineering_industry,
    questions_it_infra_cyber,
    questions_software_data,
)


def questions_business_marketing(projets: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Return 5 domain questions for business, marketing, and finance interviews."""
    return [
        {
            "question": "Comment structurez-vous et pilotez-vous une action d'acquisition ou de développement commercial par les KPI ?",
            "answer": (
                "Je définis d'abord la cible précise, la proposition de valeur et l'objectif chiffré, puis je sélectionne les canaux adaptés "
                "(SEO/SEA, prospection B2B, contenu). Je suis chaque semaine les KPI clés (taux d'ouverture/réponse, coût d'acquisition, "
                "taux de conversion par étape du tunnel) afin d'itérer rapidement sur ce qui génère le meilleur ROI."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Se focaliser sur des métriques de vanité (impressions, volume brut) sans mesurer la conversion réelle.",
        },
        {
            "question": "Quelles bonnes pratiques appliquez-vous pour fiabiliser un CRM et optimiser le suivi des opportunités ?",
            "answer": (
                "Je veille à la qualification rigoureuse des fiches contacts et comptes, à la segmentation par maturité et besoin, "
                "à la planification systématique de la prochaine action datée sur chaque opportunité et au strict respect du consentement RGPD."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Laisser s'accumuler des doublons ou des opportunités sans statut à jour, ce qui fausse les prévisions.",
        },
        {
            "question": "Quelle méthodologie adoptez-vous pour réaliser une analyse de la concurrence exploitable par l'équipe ?",
            "answer": (
                "Je construis une grille comparative factuelle (positionnement prix, offre produit, canaux d'acquisition, "
                "argumentaires et avis clients vérifiés) et j'en extrais 2 à 3 leviers de différenciation concrets directement activables."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Livrer un catalogue descriptif très long sans synthèse décisionnelle ni recommandation actionnable.",
        },
        {
            "question": "Comment concevez-vous un reporting hebdomadaire clair sous Excel ou outil BI pour votre responsable ?",
            "answer": (
                "Je pars des décisions à éclairer : je fiabilise la source de données, j'automatise les calculs récurrents, "
                "je mets en évidence les écarts par rapport à l'objectif et j'accompagne toujours les chiffres d'une analyse courte "
                "des causes et d'un plan d'action."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Présenter des tableaux bruts surchargés sans vérifier la cohérence des totaux ni proposer de piste d'action.",
        },
        {
            "question": "Comment gérez-vous plusieurs campagnes ou dossiers simultanés avec des interlocuteurs internes variés ?",
            "answer": (
                "Je maintiens un rétroplanning partagé avec jalons de validation clairs, je priorise selon l'impact métier et l'échéance, "
                "et je communique proactivement dès qu'un arbitrage ou une dépendance risque de décaler un livrable."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Attendre la date limite pour signaler un blocage ou lancer une action sans brief validé.",
        },
    ]


def questions_student_job(projets: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Return 5 practical questions for student job interviews."""
    return [
        {
            "question": "Comment réagissez-vous face à un client impatient ou mécontent en magasin ou à l'accueil ?",
            "answer": (
                "Je garde mon calme et une posture souriante, j'écoute sa demande sans l'interrompre et je reformule pour montrer "
                "qu'elle est prise en compte. J'apporte immédiatement la solution prévue par les procédures de l'établissement "
                "et, si cela dépasse mon périmètre, je passe le relais proprement à mon responsable."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Répondre sur la défensive ou improviser un geste commercial non autorisé sans prévenir l'encadrement.",
        },
        {
            "question": "Comment vous organisez-vous pour rester fiable et efficace en caisse ou au service pendant un fort rush ?",
            "answer": (
                "Je prépare mon poste en amont, je garde des gestes méthodiques sans précipitation lors de l'encaissement "
                "(vérification du montant, rendu monnaie, ticket), tout en saluant chaque client avec courtoisie pour fluidifier la file."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Confondre vitesse et précipitation au risque de commettre des erreurs de caisse ou de négliger l'accueil.",
        },
        {
            "question": "Comment garantissez-vous votre ponctualité et la compatibilité entre vos études et ce contrat ?",
            "answer": (
                "Mon emploi du temps universitaire est anticipé et structuré : je m'engage uniquement sur des créneaux "
                "où je suis pleinement disponible, je prévois toujours une marge de trajet et je préviens mon responsable "
                "très en amont de mes périodes d'examens ou de vacances où je peux renforcer mes heures."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Rester flou sur ses disponibilités réelles ou prévenir à la dernière minute d'un changement d'horaire.",
        },
        {
            "question": "Quels réflexes appliquez-vous lors de la mise en rayon, de la préparation de commandes ou d'un inventaire ?",
            "answer": (
                "Je respecte la rotation des produits (FIFO / dates limites), la propreté et l'alignement du linéaire (facing), "
                "le balisage prix, le contrôle attentif des références commandées et les gestes et postures de sécurité."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Placer les produits récents devant les anciens ou laisser des cartons encombrer le passage des clients.",
        },
        {
            "question": "Comment vous intégrez-vous rapidement dans une équipe déjà en place dès vos premiers jours ?",
            "answer": (
                "Je note attentivement les consignes d'ouverture, d'hygiène/sécurité et de fermeture dès la formation initiale, "
                "je pose des questions précises en cas de doute et je me rends disponible pour aider mes collègues dès qu'une tâche est terminée."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Attendre passivement les consignes pendant les temps calmes au lieu de prendre des initiatives utiles.",
        },
    ]


def select_technical_questions(
    cfg: Any,
    projets: Sequence[Mapping[str, str]],
    *,
    t_lower: str,
    is_job_offer: bool,
) -> list[dict[str, str]]:
    """Select the 5 domain/technical interview questions matching preset and offer text."""
    is_pentest = any(
        tok in t_lower
        for tok in ("pentest", "intrusion", "red team", "offensive", "appsec", "owasp")
    ) or (cfg.preset_id == "it_infra_cyber" and "audit" in t_lower)
    is_soc = any(
        tok in t_lower
        for tok in (
            "soc",
            "siem",
            "edr",
            "suricata",
            "blue team",
            "détection d'incidents",
            "detection d'incidents",
        )
    ) or (cfg.preset_id == "it_infra_cyber" and ("détection" in t_lower or "detection" in t_lower))
    is_grc = any(tok in t_lower for tok in ("grc", "ebios", "iso 27001", "nis2", "rssi")) or (
        cfg.preset_id == "it_infra_cyber"
        and any(tok in t_lower for tok in ("gouvernance", "conformité", "conformite", "risque"))
    )

    if is_pentest or is_soc or is_grc:
        return questions_it_infra_cyber(
            projets, is_pentest=is_pentest, is_soc=is_soc, is_grc=is_grc
        )
    if is_job_offer or cfg.preset_id == "student_job_only":
        return questions_student_job(projets)
    if cfg.preset_id == "software_data":
        return questions_software_data(projets)
    if cfg.preset_id == "engineering_industry":
        return questions_engineering_industry(projets)
    if cfg.preset_id == "business_marketing":
        return questions_business_marketing(projets)
    return questions_it_infra_cyber(projets, is_pentest=False, is_soc=False, is_grc=False)

"""Candidate context extraction and 2-minute interview pitch builder."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

FRENCH_MONTHS: tuple[str, ...] = (
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

PRESET_PITCH_ANGLES: Mapping[str, str] = {
    "it_infra_cyber": (
        "J'accorde une importance particulière à la fiabilité des infrastructures, "
        "au durcissement système et réseau, à la supervision et à la documentation opérationnelle."
    ),
    "software_data": (
        "Je privilégie une architecture logicielle lisible, des APIs robustes, "
        "des tests automatisés en intégration continue et une exploitation rigoureuse de la donnée."
    ),
    "engineering_industry": (
        "Je m'appuie sur une démarche d'ingénierie structurée mêlant respect des normes qualité et sécurité, "
        "protocoles d'essais reproductibles et amélioration continue sur le terrain."
    ),
    "business_marketing": (
        "Mon approche combine pilotage par les KPI, structuration rigoureuse du CRM, "
        "analyse fine du marché et sens du résultat commercial et client."
    ),
    "student_job_only": (
        "Sérieux, ponctuel et polyvalent, j'apprécie le contact client, le travail d'équipe "
        "et la tenue rigoureuse de mon poste même lors des fortes affluences."
    ),
}


def coerce_iso_date(value: Any) -> date | None:
    """Coerce a ``date`` or ISO ``YYYY-MM-DD`` string into a ``date`` instance."""
    if isinstance(value, date) and type(value) is date:
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def build_formation(cfg: Any) -> str:
    """Build a concise French education line from the active candidate profile."""
    cand = cfg.candidate
    level = str(cand.get("level") or "").strip()
    track = str(cand.get("track") or "").strip()
    school = str(cand.get("school") or "").strip()

    if level and track and school:
        return f"{level} ({track}) — {school}"
    if level and school:
        return f"{level} — {school}"
    if level and track:
        return f"{level} ({track})"
    if track and school:
        return f"{track} — {school}"
    if level or school or track:
        return level or school or track
    return f"Formation supérieure — {cfg.preset.label}"


def format_stage_dates(candidate: Mapping[str, Any]) -> str:
    """Format internship/apprenticeship availability dates in French."""
    start_d = coerce_iso_date(candidate.get("start"))
    end_d = coerce_iso_date(candidate.get("end"))
    raw_weeks = candidate.get("weeks")
    weeks_suffix = ""
    if isinstance(raw_weeks, int) and not isinstance(raw_weeks, bool) and raw_weeks > 0:
        weeks_suffix = f" ({raw_weeks} semaines, temps plein)"

    if start_d and end_d:
        m_start = FRENCH_MONTHS[start_d.month - 1]
        m_end = FRENCH_MONTHS[end_d.month - 1]
        if start_d.year == end_d.year:
            return f"du {start_d.day} {m_start} au {end_d.day} {m_end} {end_d.year}{weeks_suffix}"
        return (
            f"du {start_d.day} {m_start} {start_d.year} "
            f"au {end_d.day} {m_end} {end_d.year}{weeks_suffix}"
        )
    if start_d:
        m_start = FRENCH_MONTHS[start_d.month - 1]
        return f"à partir du {start_d.day} {m_start} {start_d.year}{weeks_suffix}"
    return f"selon calendrier académique{weeks_suffix}"


def _extract_experience_highlights(
    experiences: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    projets: list[dict[str, str]] = []
    for exp in experiences:
        role = str(exp.get("role") or "").strip()
        company = str(exp.get("company") or "").strip()
        dates = str(exp.get("dates") or "").strip()
        bullets = [str(b).strip() for b in (exp.get("bullets") or ()) if str(b).strip()]
        tags = [str(t).strip() for t in (exp.get("tags") or ()) if str(t).strip()]
        if not (role or company or bullets):
            continue
        nom = (
            f"{role} — {company}"
            if (role and company)
            else (role or company or "Expérience professionnelle")
        )
        if bullets:
            faits = " ; ".join(bullets)
        elif tags:
            faits = f"Compétences mobilisées : {', '.join(tags)}."
        elif dates:
            faits = f"Mission opérationnelle réalisée ({dates})."
        else:
            faits = "Réalisation opérationnelle en environnement professionnel."
        projets.append({"nom": nom, "faits": faits})
    return projets


def _extract_project_highlights(projects: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    projets: list[dict[str, str]] = []
    for proj in projects:
        p_name = str(proj.get("name") or "").strip()
        summary = str(proj.get("summary") or "").strip()
        tags = [str(t).strip() for t in (proj.get("tags") or ()) if str(t).strip()]
        if not (p_name or summary):
            continue
        nom = f"Projet — {p_name}" if p_name else "Projet technique et méthodologique"
        if summary and tags:
            faits = f"{summary} ({', '.join(tags)})"
        elif summary:
            faits = summary
        else:
            faits = f"Technologies et méthodes : {', '.join(tags)}."
        projets.append({"nom": nom, "faits": faits})
    return projets


def build_projets_phares(cfg: Any) -> list[dict[str, str]]:
    """Build at least 3 factual talking points from candidate experiences, projects, facts, or preset."""
    projets = _extract_experience_highlights(cfg.experiences)
    projets.extend(_extract_project_highlights(cfg.projects))

    for idx, fact in enumerate(cfg.facts, start=1):
        if len(projets) >= 3:
            break
        clean_fact = str(fact).strip()
        if clean_fact:
            projets.append({"nom": f"Atout du profil #{idx}", "faits": clean_fact})

    for _group_key, keywords, group_label in cfg.preset.fit_groups:
        if len(projets) >= 3:
            break
        sample_kw = ", ".join(keywords[:5])
        projets.append(
            {
                "nom": f"Mise en pratique — {group_label}",
                "faits": (
                    f"Travaux appliqués et méthodologie opérationnelle autour de : {sample_kw}. "
                    "Documentation claire et vérification systématique des résultats."
                ),
            }
        )

    for domain in cfg.preset.target_domains:
        if len(projets) >= 3:
            break
        projets.append(
            {
                "nom": f"Compétence opérationnelle — {cfg.preset.label}",
                "faits": f"Préparation ciblée en {domain}.",
            }
        )

    return projets


def build_context_from_config(cfg: Any) -> dict[str, Any]:
    """Build the factual candidate context dict from a ``CandidateProfileConfig``."""
    name = str(cfg.candidate.get("name") or "").strip() or "le candidat"
    return {
        "name": name,
        "formation": build_formation(cfg),
        "dates_stage": format_stage_dates(cfg.candidate),
        "projets_phares": build_projets_phares(cfg),
    }


def project_label(projets: Sequence[Mapping[str, str]], index: int) -> str:
    """Safely pick a highlight project title by cycling over available highlights."""
    if not projets:
        return "Réalisations académiques et projets pratiques"
    return str(projets[index % len(projets)].get("nom") or "Projet de référence")


def build_pitch_2min(
    cfg: Any,
    ctx: Mapping[str, Any],
    *,
    company: str,
    title: str,
    is_job_offer: bool,
) -> str:
    """Build a contextualized 2-minute opening interview pitch."""
    name = str(ctx.get("name") or "le candidat")
    formation = str(ctx.get("formation") or cfg.preset.label)
    projets: Sequence[Mapping[str, str]] = ctx.get("projets_phares") or ()

    intro = (
        f"Bonjour, je m'appelle {name}, actuellement en {formation}."
        if name != "le candidat"
        else f"Bonjour, mon parcours s'inscrit actuellement en {formation}."
    )
    first_highlight = ""
    if projets:
        p0 = projets[0]
        first_highlight = (
            f" J'ai notamment développé mes compétences à travers « {p0['nom']} » ({p0['faits']})."
        )
    second_highlight = ""
    if len(projets) > 1:
        p1 = projets[1]
        second_highlight = (
            f" En complément, « {p1['nom']} » m'a permis de consolider : {p1['faits']}"
        )
        if not second_highlight.endswith("."):
            second_highlight += "."

    angle = PRESET_PITCH_ANGLES.get(cfg.preset_id, PRESET_PITCH_ANGLES["it_infra_cyber"])

    if is_job_offer or cfg.preset_id == "student_job_only":
        closing = (
            " Disponible selon un planning compatible avec mes études, je souhaite mettre cette rigueur "
            f"et mon sens du service à profit chez {company} sur le poste « {title} »."
        )
    else:
        closing = (
            f" C'est cette démarche opérationnelle que je souhaite apporter à l'équipe de {company} "
            f"pour la mission « {title} » ({ctx['dates_stage']})."
        )
    return f"{intro}{first_highlight}{second_highlight} {angle}{closing}"

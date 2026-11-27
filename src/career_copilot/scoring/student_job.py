"""Student job scoring rules (distance radius, contract signals, operational skills)."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from career_copilot.scoring.models import MAX_POINTS, Score, filters_mod, hw_text

JOB_SKILL_GROUPS: tuple[tuple[tuple[str, ...], str, int], ...] = (
    (
        ("caisse", "encaissement", "monnaie", "hote de caisse"),
        "Tenue de caisse & encaissement",
        8,
    ),
    (
        ("rayon", "mise en rayon", "inventaire", "stock", "marchandise"),
        "Mise en rayon & inventaires",
        8,
    ),
    (("client", "accueil", "vente", "conseil", "sav"), "Accueil client & SAV", 8),
    (
        (
            "commande",
            "colis",
            "tri",
            "manutention",
            "preparation",
            "logistique",
            "entrepot",
        ),
        "Rigueur opérationnelle & cadence",
        8,
    ),
    (
        ("noel", "saisonnier", "fetes", "weekend", "week-end", "renfort", "etudiant"),
        "Disponibilité week-end / temps partiel / vacances",
        6,
    ),
    (
        ("dossier", "controle", "saisie", "administratif", "verification"),
        "Contrôle de dossiers & suivi administratif",
        6,
    ),
)


def evaluate_student_job_location(
    offer: Any,
) -> tuple[int, str, bool, str, str, float | None]:
    """Compute student-job proximity against active candidate zones."""
    basins_mod = importlib.import_module("hellowork.basins")
    geo = importlib.import_module("hellowork.geo")
    lat, lon = offer.latitude, offer.longitude
    if lat is None or lon is None or not basins_mod.ZONES:
        return (
            0,
            f"localisation à vérifier ({offer.location})",
            False,
            "unknown",
            "",
            None,
        )

    nearest, raw_dist = geo.nearest_zone(float(lat), float(lon))
    dist = round(raw_dist, 1)
    zone_name = str(nearest["name"])
    if dist <= basins_mod.JOB_RADIUS_KM:
        place_points, rejected_place, loc_status = 15, False, "in_zone"
        place_reason = (
            f"dans le rayon job étudiant ({dist} km <= "
            f"{basins_mod.JOB_RADIUS_KM:.0f} km de {zone_name})"
        )
    else:
        place_points, rejected_place, loc_status = 0, True, "out_zone"
        place_reason = (
            f"hors périmètre job étudiant ({dist} km > "
            f"{basins_mod.JOB_RADIUS_KM:.0f} km de {zone_name})"
        )
    offer.zone = zone_name
    offer.distance_km = dist
    offer.location_status = loc_status
    return place_points, place_reason, rejected_place, loc_status, zone_name, dist


def evaluate_student_job_contract(
    offer: Any,
    full_text: str,
    folded_title: str,
    folded_text: str,
    folded_contract: str,
) -> tuple[int, str, bool]:
    """Validate student-job contract and title compatibility."""
    flt = filters_mod()
    fold = hw_text().fold
    target_dict = {
        "title": offer.title,
        "text": full_text,
        "contract_type": offer.contract,
        "source": offer.apply_mode or "hellowork",
    }
    if any(w in f"{folded_contract} {folded_title}" for w in ("alternance", "apprentissage")):
        return 0, "alternance / apprentissage incompatible", True
    if flt.excluded(full_text) or any(fold(w) in folded_title for w in flt.JOB_REJECT):
        return 0, "poste écarté des critères job étudiant", True
    if flt._missing_required_cert(folded_text):
        return 0, "certification / diplôme métier manquant (CACES/CAP)", True
    if flt._incompatible_job_contract(target_dict, folded_title, folded_text):
        return 0, "contrat CDI temps plein sans signal étudiant/saisonnier", True
    if not any(fold(w) in folded_title for w in (*flt.JOB_MUST, "job etudiant", "etudiant")):
        return 0, "intitulé hors job étudiant ciblé", True
    sanitized_text = flt._strip_daily_hour_ranges(f"{folded_title} {folded_text}".strip())
    explicit_signals = (
        *flt.PART_TIME_SIGNALS,
        *flt.HOLIDAY_SEASONAL_SIGNALS,
        "etudiant",
        "etudiante",
    )
    if any(flt._has_bounded_token(sanitized_text, sig) for sig in explicit_signals):
        return 25, "contrat job étudiant / saisonnier / temps partiel compatible", False
    return 15, "job éligible (horaires temps partiel / étudiant à confirmer)", False


def evaluate_student_job(
    offer: Any,
    *,
    freshness_fn: Callable[[Any], tuple[int, str]],
) -> Score:
    """Evaluate a student job offer within active geographic radii."""
    fold = hw_text().fold
    missions_text = offer.missions or offer.description
    full_text = " ".join(
        part for part in (offer.title, missions_text, offer.profile, offer.benefits) if part
    )
    folded_title = fold(offer.title)
    folded_text = fold(full_text)
    folded_contract = fold(offer.contract)

    (
        place_points,
        place_reason,
        rejected_place,
        loc_status,
        zone_name,
        dist,
    ) = evaluate_student_job_location(offer)
    contract_points, contract_reason, rejected_contract = evaluate_student_job_contract(
        offer, full_text, folded_title, folded_text, folded_contract
    )

    matched: list[str] = []
    skill_weight = 16 if not rejected_contract else 0
    for markers, label, weight in JOB_SKILL_GROUPS:
        if any(m in folded_text for m in markers):
            skill_weight += weight
            if label not in matched:
                matched.append(label)
    skill_points = min(MAX_POINTS["compétences"], skill_weight)
    level_points = MAX_POINTS["niveau"]
    fresh_points, fresh_reason = freshness_fn(offer)

    parts = {
        "contrat": contract_points,
        "lieu": place_points,
        "compétences": skill_points,
        "niveau": level_points,
        "fraîcheur": fresh_points,
    }
    total = max(0, min(100, sum(parts.values())))
    if contract_points < 25 and not rejected_contract:
        total = min(total, 74)
    if loc_status == "unknown":
        total = min(total, 79)
    reasons = [item for item in (contract_reason, place_reason, fresh_reason) if item]
    rejected = rejected_contract or rejected_place
    reject_reason = (
        contract_reason if rejected_contract else (place_reason if rejected_place else "")
    )
    if rejected:
        total = min(total, 20)

    return Score(
        value=total,
        parts=parts,
        reasons=reasons,
        gaps=[],
        matched=matched[:6],
        rejected=rejected,
        reject_reason=reject_reason,
        zone=zone_name,
        distance_km=dist,
        location_status=loc_status,
    )

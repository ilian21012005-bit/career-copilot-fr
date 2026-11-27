"""Core deterministic 5-block scoring engine for stage, alternance, and student jobs."""

from __future__ import annotations

import importlib
from typing import Any

from career_copilot.profile.presets_access import get_presets_module
from career_copilot.scoring.models import (
    IT_SOFT_KEEP_MARKERS,
    LEVEL_MARKERS,
    MAX_POINTS,
    Score,
    campaign_of,
    has_alternance_marker,
    hw_profile,
    hw_text,
    offer_blob,
)
from career_copilot.scoring.rules import (
    accepts_bac3,
    candidate_level_rank,
    deep_fit_flags,
    duration_verdict,
    exclusive_bac5_inge,
    mission_reject,
)
from career_copilot.scoring.student_job import evaluate_student_job


def score_freshness(offer: Any) -> tuple[int, str]:
    days = offer.posted_days
    if days is None:
        return 5, ""
    if days <= 3:
        return 10, "annonce très récente"
    if days <= 7:
        return 9, "annonce de la semaine"
    if days <= 14:
        return 7, ""
    if days <= 30:
        return 4, "annonce de plus de deux semaines"
    return 1, "annonce ancienne"


def score_contract(offer: Any) -> tuple[int, str, bool]:
    text_mod = hw_text()
    prof = hw_profile()
    cfg = prof.active_config()
    folded = text_mod.fold(f"{offer.contract} {offer.title}")
    accepts_alt = "alternance" in cfg.contracts
    accepts_stage = "stage" in cfg.contracts
    is_alt = has_alternance_marker(folded)
    is_stage = (
        "stage" in folded
        or text_mod.has(folded, "stagiaire")
        or text_mod.has(folded, "intern")
        or text_mod.has(folded, "internship")
    )

    if is_alt:
        if accepts_alt:
            return 25, "contrat d'alternance / apprentissage ciblé", False
        return 0, "ce n'est pas un stage (alternance ou apprentissage)", True

    if any(
        text_mod.has(folded, word) for word in ("cdi", "cdd", "interim", "freelance", "independant")
    ):
        msg = "ce n'est pas un stage ni une alternance" if accepts_alt else "ce n'est pas un stage"
        return 0, msg, True

    if is_stage:
        if not accepts_stage:
            return (
                0,
                "stage écarté (contrat stage non sélectionné dans le profil)",
                True,
            )
        return 25, "stage confirmé", False

    if any(text_mod.fold(word) in folded for word in prof.EXCLUDE_CONTRACTS):
        return 0, "type de contrat exclu par le profil", True

    return 10, "type de contrat imprécis dans l'annonce", False


def score_location(offer: Any) -> tuple[int, str, bool, dict[str, Any]]:
    """Return `(points, reason, rejected, location_dict)`."""
    basins_mod = importlib.import_module("hellowork.basins")
    geo = importlib.import_module("hellowork.geo")
    location = geo.locate(offer.latitude, offer.longitude)
    where = offer.location
    if location["status"] == "unknown":
        return 0, f"localisation à vérifier ({where})", False, location
    if location["status"] == "in_zone":
        return (
            15,
            f"dans la zone {location['zone']} ({location['distance_km']} km à vol d'oiseau)",
            False,
            location,
        )
    zone_count = len(basins_mod.ZONES)
    out_prefix = (
        "hors des trois zones" if zone_count == 3 else f"hors des {zone_count} zones configurées"
    )
    return (
        0,
        f"{out_prefix} : {where}, le plus proche est {location['zone']} à {location['distance_km']} km",
        True,
        location,
    )


def score_skills(text: str) -> tuple[int, list[str], list[str], str]:
    text_mod = hw_text()
    prof = hw_profile()
    matched: list[str] = []
    weight = 0
    for skill, points in prof.SKILLS.items():
        if text_mod.has(text, skill):
            matched.append(skill)
            weight += points
    matched.sort(key=lambda skill: -prof.SKILLS[skill])
    if weight == 0:
        return 0, [], [], "aucune compétence du profil reconnue dans l'annonce"
    points = min(MAX_POINTS["compétences"], round(MAX_POINTS["compétences"] * weight / 40))
    owned = {text_mod.fold(item) for item in prof.OWNED}
    gaps = [skill for skill in matched if text_mod.fold(skill) not in owned]
    return points, matched, gaps, f"{len(matched)} compétence(s) du profil retrouvée(s)"


def score_level(text: str) -> tuple[int, int, list[str]]:
    text_mod = hw_text()
    prof = hw_profile()
    folded = text_mod.fold(text)
    cand_rank = candidate_level_rank()
    bac3_ok = accepts_bac3(folded)
    penalty = 0
    reasons: list[str] = []
    applied_labels: set[str] = set()
    for marker, cost, label in prof.LEVEL_PENALTIES:
        m_fold = text_mod.fold(marker)
        if m_fold not in folded or label in applied_labels:
            continue
        is_edu_level = any(word in label.lower() for word in LEVEL_MARKERS)
        if is_edu_level:
            if "doctorat" in m_fold and cand_rank >= 5:
                pass
            elif (
                cand_rank >= 5
                and "doctorat" not in m_fold
                or cand_rank == 4
                and m_fold in ("master", "ecole d'ingenieur", "école d'ingénieur")
                or bac3_ok
                and cand_rank >= 3
            ):
                continue
        penalty += cost
        applied_labels.add(label)
        reasons.append(label)
    if bac3_ok and cand_rank <= 3:
        reasons.append("Bac+3 accepté par l'annonce")
    elif cand_rank >= 4 and not penalty:
        reasons.append("Niveau Master / Bac+5 compatible")
    return max(0, MAX_POINTS["niveau"] - penalty // 4), penalty, reasons


def apply_fit_caps(
    total: int,
    *,
    offer: Any,
    missions_text: str,
    level_penalty: int,
    contract_points: int,
    rejected_contract: bool,
    duration_rejected: bool,
    location: dict[str, Any],
    preset: Any,
    reasons: list[str],
) -> int:
    """Apply level, duration, location, contract, and preset scope score caps."""
    text_mod = hw_text()
    presets_mod = get_presets_module()
    blob_all = offer_blob(offer)
    cand_rank = candidate_level_rank()
    soft_bac5 = cand_rank <= 3 and any(
        x in blob_all for x in ("bac+5", "bac +5", "bac+4/5", "master 2")
    )
    bac3_ok = accepts_bac3(blob_all) or cand_rank >= 4
    if exclusive_bac5_inge(blob_all):
        ops = any(text_mod.has(blob_all, k) for k in preset.operational_keep)
        if ops:
            total = min(total, 68)
            reasons.append(
                "Bac+5/ingé sans Bac+3 explicite mais mission opérationnelle ciblée : soft keep"
            )
        else:
            total = min(total, 45)
            reasons.append("Bac+5/ingé exclusif (score plafonné bas — candidature improbable)")
    elif (level_penalty >= 30 or soft_bac5) and not bac3_ok:
        total = min(total, 60)
        reasons.append("niveau Bac+5/Master possible : gardé en soft, score plafonné")
    elif level_penalty >= 15 and not bac3_ok:
        total = min(total, 79)
        reasons.append("niveau demandé au-dessus du Bac+3 (score plafonné)")

    if duration_rejected:
        total = min(total, 25)
        weeks = hw_profile().CANDIDATE["weeks"]
        reasons.append(f"ÉCART NET — ne pas candidater sans accord écrit sur {weeks} semaines")

    if location["status"] == "unknown":
        total = min(total, 79)

    if contract_points < 25 and not rejected_contract:
        total = min(total, 79)
        reasons.append("contrat ciblé non confirmé : vérification nécessaire")

    focus_text = " ".join(part for part in (offer.title, missions_text) if part)
    if not any(text_mod.has(focus_text, keyword) for keyword in preset.target_keywords):
        total = min(total, 55)
        reasons.append(f"poste hors périmètre reconnu ({preset.label})")

    keep_markers = (
        IT_SOFT_KEEP_MARKERS
        if preset.id == presets_mod.DEFAULT_PRESET_ID
        else preset.operational_keep
    )
    if any(text_mod.fold(m) in blob_all for m in preset.off_target_soft) and not any(
        text_mod.has(blob_all, k) for k in keep_markers
    ):
        total = min(total, 58)
        reasons.append("mission éloignée du cœur métier visé (plafond soft)")
    return total


def evaluate(offer: Any) -> Score:
    """Compute a transparent 0-100 Score with reasons, gaps, and rejection flags."""
    cfg = hw_profile().active_config()
    preset = cfg.preset
    campaign = campaign_of(offer)
    if campaign == "job":
        return evaluate_student_job(offer, freshness_fn=score_freshness)

    missions_text = offer.missions or offer.description
    text = " ".join(
        part for part in (offer.title, missions_text, offer.profile, offer.benefits) if part
    )
    contract_points, contract_reason, rejected_contract = score_contract(offer)
    place_points, place_reason, rejected_place, location = score_location(offer)
    skill_points, matched, gaps, skill_reason = score_skills(text)
    level_points, level_penalty, level_reasons = score_level(offer.profile or text)
    fresh_points, fresh_reason = score_freshness(offer)

    parts = {
        "contrat": contract_points,
        "lieu": place_points,
        "compétences": skill_points,
        "niveau": level_points,
        "fraîcheur": fresh_points,
    }
    total = max(0, min(100, sum(parts.values())))
    reasons = [item for item in (contract_reason, place_reason, skill_reason, fresh_reason) if item]
    reasons.extend(level_reasons)

    if campaign == "stage":
        duration_rejected, duration_reason, duration_notes = duration_verdict(offer)
        reasons.extend(duration_notes)
    else:
        duration_rejected, duration_reason = False, ""

    reasons.extend(deep_fit_flags(offer))
    mission_rejected, mission_reason = mission_reject(offer)
    if mission_reason:
        reasons.append(mission_reason)

    total = apply_fit_caps(
        total,
        offer=offer,
        missions_text=missions_text,
        level_penalty=level_penalty,
        contract_points=contract_points,
        rejected_contract=rejected_contract,
        duration_rejected=duration_rejected,
        location=location,
        preset=preset,
        reasons=reasons,
    )

    rejected = rejected_contract or rejected_place or duration_rejected or mission_rejected
    reject_reason = (
        contract_reason
        if rejected_contract
        else place_reason
        if rejected_place
        else duration_reason
        if duration_rejected
        else mission_reason
        if mission_rejected
        else ""
    )
    if rejected:
        total = min(total, 20)

    return Score(
        value=total,
        parts=parts,
        reasons=reasons,
        gaps=gaps,
        matched=matched,
        rejected=rejected,
        reject_reason=reject_reason,
        zone=location["zone"],
        distance_km=location["distance_km"],
        location_status=location["status"],
    )

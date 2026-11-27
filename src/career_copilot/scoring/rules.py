"""Duration, education level, and off-target mission rules for offer scoring."""

from __future__ import annotations

import re
from typing import Any

from career_copilot.profile.presets_access import get_presets_module
from career_copilot.scoring.models import (
    BAC3_ACCEPTED,
    DEVELOPMENT_ROLE_MARKERS,
    RESEARCH_FOCUS_MARKERS,
    filters_mod,
    hw_profile,
    hw_text,
    offer_blob,
)

_FRENCH_NUMBER_WORDS: dict[str, int] = {
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
}


def parse_duration_weeks(text: str) -> tuple[int | None, str]:
    """Extract announced internship length in weeks when the offer is explicit."""
    folded = hw_text().fold(text)
    m = re.search(
        r"\b(?:de\s+)?(\d{1,2})\s*(?:a|à|-|–)\s*(\d{1,2})\s*(semaines?|mois)\b",
        folded,
    )
    if m:
        lo, hi = sorted((int(m.group(1)), int(m.group(2))))
        unit = m.group(3)
        mul = 1 if unit.startswith("semaine") else 4
        return lo * mul, f"{lo} à {hi} {unit}"

    m = re.search(
        r"\b(?:duree\s*(?:du stage\s*)?(?::|de|d\'?|est)?\s*)?(\d{1,2})\s*(semaines?|mois)\b",
        folded,
    )
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        weeks = n if unit.startswith("semaine") else n * 4
        return weeks, f"{n} {unit}"

    m = re.search(
        r"\b(?:ces|de|d'|du|pendant|sur|duree(?:\s+du\s+stage)?(?:\s*(?::|de))?\s*)?"
        r"(deux|trois|quatre|cinq|six|sept|huit|neuf|dix|onze|douze)\s+mois\b",
        folded,
    )
    if m:
        return _FRENCH_NUMBER_WORDS[m.group(1)] * 4, f"{m.group(1)} mois"
    return None, ""


def parse_duration_range(text: str) -> tuple[int | None, int | None, str]:
    """Return `(min_weeks, max_weeks, label)` when a duration range is present."""
    folded = hw_text().fold(text)
    m = re.search(
        r"\b(?:de\s+)?(\d{1,2})\s*(?:a|à|-|–)\s*(\d{1,2})\s*(semaines?|mois)\b",
        folded,
    )
    if not m:
        weeks, label = parse_duration_weeks(text)
        return weeks, weeks, label
    lo, hi = sorted((int(m.group(1)), int(m.group(2))))
    unit = m.group(3)
    mul = 1 if unit.startswith("semaine") else 4
    return lo * mul, hi * mul, f"{lo} à {hi} {unit}"


def duration_verdict(offer: Any) -> tuple[bool, str, list[str]]:
    """Hard-check duration against the candidate internship convention."""
    prof = hw_profile()
    blob = f"{offer.description} {offer.missions} {offer.profile} {offer.benefits} {offer.title}"
    lo, hi, label = parse_duration_range(blob)
    period = f"{prof.CANDIDATE['start'].isoformat()} au {prof.CANDIDATE['end'].isoformat()}"
    cand = prof.CANDIDATE["weeks"]
    notes: list[str] = []
    if lo is None:
        notes.append(
            "durée et dates du stage à vérifier avec le recruteur "
            f"(disponibilité : {period}, {cand} semaines)"
        )
        return False, "", notes
    notes.append(f"durée annoncée dans l’offre : {label} (~{lo}–{hi} sem.)")
    if lo > cand + 2:
        reason = (
            f"durée incompatible : l’offre annonce {label} (min ~{lo} sem.) "
            f"alors que la convention est de {cand} semaines ({period})"
        )
        notes.append(reason)
        return True, reason, notes
    if hi is not None and hi > cand + 2:
        notes.append(
            f"durée haute de la fourchette (~{hi} sem.) au-delà de la convention — "
            f"négocier {cand} semaines par écrit avant d’accepter"
        )
    if lo < cand - 4:
        notes.append(
            f"durée plus courte que la convention ({label}) — à confirmer avec l'établissement"
        )
    else:
        notes.append(f"plancher de durée compatible avec la convention ({cand} semaines)")
    return False, "", notes


def stage_schedule_notes(offer: Any) -> list[str]:
    _, _, notes = duration_verdict(offer)
    return notes


def candidate_level_rank(cfg: Any = None) -> int:
    """Return estimated study level rank (1..5, default 3 = Bac+3)."""
    if cfg is None:
        cfg = hw_profile().active_config()
    raw = hw_text().fold(str((cfg.candidate or {}).get("level") or ""))
    if not raw:
        return 3
    level_tiers = (
        (
            5,
            (
                "bac+5",
                "bac +5",
                "bac + 5",
                "master 2",
                "master2",
                "m2",
                "ingenieur",
                "pfe",
                "doctorat",
                "phd",
                "niveau 7",
            ),
        ),
        (4, ("bac+4", "bac +4", "master 1", "master1", "m1", "master")),
        (3, ("bac+3", "bac +3", "but 3", "but3", "licence", "bachelor", "l3", "but")),
        (2, ("bac+2", "bac +2", "bts", "dut", "but 2", "but2", "l2", "deug")),
        (1, ("bac+1", "bac +1", "but 1", "but1", "l1", "bac")),
    )
    for rank, tokens in level_tiers:
        if any(tok in raw for tok in tokens):
            return rank
    return 3


def accepts_bac3(blob: str) -> bool:
    return any(marker in blob for marker in BAC3_ACCEPTED) or bool(
        re.search(
            r"\blicence\b(?!\s+(?:de\s+|d['’])?(?:logiciel|logicielle|windows|office|microsoft|conducteur|conduire))"
            r"|\bbut\b|\bbachelor\b|\bbac\s*\+\s*2\b|\bbac\s*\+\s*3\b",
            blob,
        )
    )


def exclusive_bac5_inge(blob: str) -> bool:
    """Detect Bac+5 / engineering-school exclusive postings when candidate is <= Bac+3."""
    if candidate_level_rank() >= 4 or accepts_bac3(blob):
        return False
    bac5 = any(x in blob for x in ("bac+5", "bac +5", "bac+4/5", "master 2", "master2", "bac + 5"))
    inge = any(
        x in blob
        for x in (
            "ecole d'ingenieur",
            "ecole d ingenieurs",
            "derniere annee d'ecole",
            "ingenieur bac+5",
            "stage de fin d'etudes",
            "stage de fin d etudes",
            "pfe ",
            "projet de fin d'etudes",
        )
    )
    title_inge = "ingenieur" in hw_text().fold(blob[:220]) or "ingénieur" in blob[:220]
    return bac5 and (inge or title_inge)


def off_target_hard(blob: str, title: str, focus: str = "") -> str:
    """Reject clearly off-target postings based on the active career preset."""
    text_mod = hw_text()
    presets_mod = get_presets_module()
    cfg = hw_profile().active_config()
    preset = cfg.preset
    title_f = text_mod.fold(title)
    focus_f = text_mod.fold(focus) if focus else title_f

    for marker in preset.off_target_hard:
        m_f = text_mod.fold(marker)
        if not m_f:
            continue
        if m_f in RESEARCH_FOCUS_MARKERS:
            if text_mod.has(title_f, m_f) or text_mod.has(focus_f, m_f):
                return f"hors cible ({preset.id}) : {marker}"
        elif text_mod.has(title_f, m_f) or m_f in title_f:
            return f"hors cible ({preset.id}) : {marker}"

    for custom in cfg.custom_exclude_keywords:
        c_f = text_mod.fold(custom)
        if c_f and (text_mod.has(title_f, c_f) or c_f in title_f):
            return f"mot-clé exclu par le profil : {custom}"

    if not cfg.allow_pure_software_dev:
        ops_markers = (
            filters_mod().OPERATIONAL_FOCUS_MARKERS
            if preset.id == presets_mod.DEFAULT_PRESET_ID
            else tuple(text_mod.fold(k) for k in preset.operational_keep)
        )
        if any(marker in title_f for marker in DEVELOPMENT_ROLE_MARKERS) and not any(
            marker in focus_f for marker in ops_markers
        ):
            return "développement logiciel pur, hors périmètre demandé"

    if (
        preset.id == presets_mod.DEFAULT_PRESET_ID
        and text_mod.has(title_f, "soc")
        and "fpga" in title_f
        and "cyber" not in title_f
    ):
        return "hors cible : SoC/FPGA (pas un SOC cybersécurité)"
    return ""


def deep_fit_flags(offer: Any) -> list[str]:
    """Collect vigilance signals (education level, pre-hire CDI, soft off-target markers)."""
    text_mod = hw_text()
    presets_mod = get_presets_module()
    preset = hw_profile().active_preset()
    blob = offer_blob(offer)
    flags: list[str] = []
    if any(
        text_mod.has(blob, marker)
        for marker in ("poursuite en cdi", "deboucher sur un cdi", "embauche en cdi")
    ):
        flags.append("annonce orientée poursuite CDI (pré-embauche)")
    cand_rank = candidate_level_rank()
    if cand_rank <= 3 and (
        "derniere annee d'ecole d'ingenieur" in blob
        or "derniere annee d ecole d ingenieurs" in blob
    ):
        flags.append("profil ciblé : dernière année d’école d’ingénieur")
    if (
        cand_rank <= 3
        and text_mod.has(blob, "ecole d'ingenieur")
        and not accepts_bac3(blob)
        and "universite" not in blob
        and "universitaire" not in blob
    ):
        flags.append("école d’ingénieur exigée sans ouverture Bac+3/BUT explicite")
    if exclusive_bac5_inge(blob):
        flags.append("Bac+5 / fin d'études ingénieur sans ouverture Bac+3 (pénalité forte)")
    for marker in preset.off_target_soft:
        if text_mod.fold(marker) in blob:
            flags.append(f"orientation éloignée du preset ({preset.id}) : {marker}")
            break
    if preset.id == presets_mod.DEFAULT_PRESET_ID:
        grc_hits = sum(
            1
            for k in ("ebios", "iso 27001", "iso27001", "nis2", "dora", "ai act", "rssi")
            if k in blob
        )
        soc_hits = sum(
            1
            for k in ("soc", "siem", "edr", "soar", "analyste", "blue team")
            if text_mod.has(blob, k)
        )
        if grc_hits >= 3 and soc_hits <= 1:
            flags.append("mission GRC/conseil (référentiels) plus que SOC opérationnel")
    return flags


def mission_reject(offer: Any) -> tuple[bool, str]:
    """Reject offers clearly outside the active preset scope."""
    text_mod = hw_text()
    preset = hw_profile().active_preset()
    blob = offer_blob(offer)
    focus = " ".join(x for x in (offer.title, offer.missions) if x)
    hard = off_target_hard(blob, offer.title, focus)
    if hard:
        return True, hard
    if exclusive_bac5_inge(blob) and not any(
        text_mod.has(blob, k) for k in preset.operational_keep
    ):
        return (
            True,
            "Bac+5 / école d'ingénieur exclusif sans mission opérationnelle ciblée",
        )
    return False, ""

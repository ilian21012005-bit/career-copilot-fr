"""Candidate identity header, French dateline, subject, and availability formatting."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from career_copilot.letters.text_utils import fold, is_alternance_text, is_stage
from career_copilot.profile import CandidateProfileConfig

MONTHS: tuple[str, ...] = (
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


def candidate_name(
    cfg: CandidateProfileConfig,
    *,
    name_override: str = "",
    sender_name: str = "",
) -> str:
    """Resolve candidate display name (`override` > `candidate.name` > `SENDER_NAME` > fallback)."""
    if name_override:
        return name_override
    name = str(cfg.candidate.get("name") or "").strip()
    if name:
        return name
    env_sender = os.getenv("SENDER_NAME", "").strip()
    if env_sender:
        return env_sender
    sender = str(sender_name or "").strip()
    if sender and sender.lower() != "candidat":
        return sender
    return "Le candidat"


def header_line(
    cfg: CandidateProfileConfig,
    *,
    name_override: str = "",
    sender_name: str = "",
) -> str:
    """Build dynamic contact header line from the active candidate profile."""
    cand = cfg.candidate
    parts = [
        str(val).strip()
        for val in (
            cand.get("name") or (name_override if name_override else ""),
            cand.get("home"),
            cand.get("phone"),
            cand.get("email"),
        )
        if val and str(val).strip()
    ]
    return (
        " | ".join(parts)
        if parts
        else candidate_name(cfg, name_override=name_override, sender_name=sender_name)
    )


def dating_city(cfg: CandidateProfileConfig) -> str:
    """Extract clean city name for letter dateline (`candidate.home` or `zones[0].name`)."""
    raw_home = str(cfg.candidate.get("home") or "").split("(")[0].split(",")[0].strip()
    if raw_home:
        return raw_home
    if cfg.configured and cfg.zones:
        zone_city = str(cfg.zones[0].get("name") or "").split("(")[0].split(",")[0].strip()
        if zone_city:
            return zone_city
    return ""


def dateline(cfg: CandidateProfileConfig, *, today: date | None = None) -> str:
    """Format French letter dateline (« Lyon, le ... » or fallback « Fait le ... »)."""
    day_ref = today or date.today()
    date_label = f"{day_ref.day} {MONTHS[day_ref.month - 1]} {day_ref.year}"
    city = dating_city(cfg)
    return f"{city}, le {date_label}" if city else f"Fait le {date_label}"


def format_date_fr(raw_date: Any) -> str:
    """Format an ISO date string or `datetime.date` in French (e.g. « 1er mars 2027 »)."""
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
    return f"{day_txt} {MONTHS[parsed.month - 1]} {parsed.year}"


def campaign_of_target(target: dict[str, Any], title: str) -> str:
    """Resolve target campaign (`alternance`, `stage`, or `job`)."""
    explicit = fold(str(target.get("campaign") or "")).strip()
    if explicit == "alternance":
        return "alternance"
    if explicit == "job":
        return "job"
    contract_blob = " ".join(
        str(target.get(key) or "") for key in ("type", "contract", "contract_type")
    )
    if is_alternance_text(f"{contract_blob} {title}"):
        return "alternance"
    if explicit == "stage" or is_stage(target, title):
        return "stage"
    return "job"


def subject_for(campaign: str, short: str, company: str) -> str:
    """Build contract-specific application subject line."""
    if campaign == "alternance":
        return f"Candidature en alternance – {short} – {company}"
    if campaign == "stage":
        return f"Candidature au stage – {short} – {company}"
    return f"Candidature – {short} – {company}"


def is_candidate_bac3_or_less(cfg: CandidateProfileConfig) -> bool:
    level_folded = fold(str(cfg.candidate.get("level") or ""))
    return not any(
        tok in level_folded
        for tok in ("bac+5", "bac +5", "bac+4", "bac +4", "master", "m1", "m2", "ingenieur")
    )


def education_intro(cfg: CandidateProfileConfig) -> str:
    cand = cfg.candidate
    level = str(cand.get("level") or "").strip()
    track = str(cand.get("track") or cfg.preset.label or "").strip()
    school = str(cand.get("school") or "").strip()
    if level and track and fold(track).startswith(fold(level)):
        edu = track
    elif level and track:
        edu = f"{level} ({track})"
    else:
        edu = level or track or "formation supérieure"
    if school:
        return f"Actuellement en {edu} à {school}"
    return f"Actuellement en {edu}"


def mobility_closing(cfg: CandidateProfileConfig) -> str:
    city = dating_city(cfg)
    mobility = str(cfg.candidate.get("mobility") or "").strip()
    if not mobility and cfg.configured and cfg.zones:
        mobility = ", ".join(
            str(zone.get("name") or "").strip()
            for zone in cfg.zones
            if str(zone.get("name") or "").strip()
        )
    if city and mobility and fold(city) != fold(mobility):
        base = f"Basé à {city}, je suis mobile sur {mobility} et disponible sur toute la période prévue."
    elif city:
        base = f"Basé à {city}, je suis disponible sur toute la période prévue."
    elif mobility:
        base = f"Mobile sur {mobility}, je suis disponible sur toute la période prévue."
    else:
        base = "Je suis disponible sur toute la période prévue."
    return f"{base} Je serais heureux d’en parler avec vous lors d’un entretien."


def job_availability_text(cfg: CandidateProfileConfig) -> str:
    jfa = cfg.job_form_answers or {}
    for key in ("disponibilité", "Disponibilité", "disponibilite", "Disponibilite"):
        val = str(jfa.get(key) or "").strip()
        if val:
            return val
    return "à temps partiel (week-ends et soirs) ainsi que pendant les vacances scolaires"


def job_availability_paragraph(cfg: CandidateProfileConfig) -> str:
    raw = job_availability_text(cfg).rstrip(".")
    lowered = raw.lower()
    if lowered.startswith("je "):
        first = raw[0].upper() + raw[1:] + "."
    elif lowered.startswith("disponible"):
        first = f"Je suis {raw[0].lower() + raw[1:]}."
    elif lowered.startswith(("à ", "a ", "dès ", "des ")):
        first = f"Je suis disponible {raw}."
    else:
        first = f"Je suis disponible : {raw}."
    return f"{first} Je peux commencer rapidement et je reste disponible pour un entretien."

"""Scoring data model, campaign detection, and public constants."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any

from career_copilot.profile.presets_access import get_presets_module

MAX_POINTS: dict[str, int] = {
    "contrat": 25,
    "lieu": 15,
    "compétences": 40,
    "niveau": 10,
    "fraîcheur": 10,
}

BAC3_ACCEPTED: tuple[str, ...] = (
    "bac+3",
    "bac +3",
    "bac+2/3",
    "bac+3/5",
    "but 3",
    "but3",
    "niveau 6",
)

LEVEL_MARKERS: tuple[str, ...] = ("bac+", "bac +", "master", "école", "ecole", "doctorat")

ALTERNANCE_MARKERS: tuple[str, ...] = (
    "alternance",
    "apprentissage",
    "contrat pro",
    "professionnalisation",
    "alternant",
    "apprenti",
)

RESEARCH_FOCUS_MARKERS: frozenset[str] = frozenset(
    {"verification formelle", "methodes formelles", "cryptologie"}
)

IT_SOFT_KEEP_MARKERS: tuple[str, ...] = (
    "soc",
    "siem",
    "edr",
    "administrateur",
    "reseau",
    "systeme",
    "sysadmin",
    "devops",
    "devsecops",
    "cloud",
    "support",
    "helpdesk",
    "itsm",
    "exploitation",
    "infrastructure",
)

DEVELOPMENT_ROLE_MARKERS: tuple[str, ...] = (
    "developpeur",
    "developer",
    "software engineer",
    "software development",
    "developpement logiciel",
    "developpement informatique",
    "developpement web",
    "developpement applicatif",
    "developpement mobile",
    "low-code",
    "low code",
    "citizen developer",
)

_PRESETS_MOD = get_presets_module()
_DEFAULT_PRESET = _PRESETS_MOD.get_preset(_PRESETS_MOD.DEFAULT_PRESET_ID)
TARGET_KEYWORDS: tuple[str, ...] = _DEFAULT_PRESET.target_keywords
OFF_TARGET_HARD: tuple[str, ...] = _DEFAULT_PRESET.off_target_hard
OFF_TARGET_SOFT: tuple[str, ...] = _DEFAULT_PRESET.off_target_soft
OPERATIONAL_KEEP: tuple[str, ...] = _DEFAULT_PRESET.operational_keep


def hw_profile() -> Any:
    return importlib.import_module("hellowork.profile")


def hw_text() -> Any:
    return importlib.import_module("hellowork.text")


def filters_mod() -> Any:
    return importlib.import_module("filters")


@dataclass
class Score:
    value: int
    parts: dict[str, int]
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    rejected: bool = False
    reject_reason: str = ""
    zone: str = ""
    distance_km: float | None = None
    location_status: str = "unknown"

    @property
    def shortlisted(self) -> bool:
        return (
            not self.rejected
            and self.location_status != "unknown"
            and self.value >= hw_profile().MIN_SCORE
        )

    @property
    def verdict(self) -> str:
        if self.rejected:
            return "écartée"
        if self.location_status == "unknown":
            return "à vérifier"
        if self.value >= hw_profile().MIN_SCORE:
            return "à préparer"
        if self.value >= 60:
            return "limite"
        return "faible"

    def explain(self) -> str:
        lines = [f"{self.value}/100 — {self.verdict}"]
        for key, points in self.parts.items():
            lines.append(f"  {key:<12} {points:>2}/{MAX_POINTS[key]}")
        if self.reject_reason:
            lines.append(f"  motif d'écart : {self.reject_reason}")
        for reason in self.reasons:
            lines.append(f"  · {reason}")
        if self.matched:
            lines.append("  compétences vues : " + ", ".join(self.matched[:12]))
        if self.gaps:
            lines.append("  à ne pas prétendre : " + ", ".join(self.gaps[:8]))
        return "\n".join(lines)


def has_alternance_marker(text: str) -> bool:
    folded = hw_text().fold(text)
    return any(marker in folded for marker in ALTERNANCE_MARKERS)


def offer_blob(offer: Any) -> str:
    return hw_text().fold(
        f"{offer.title} {offer.description} {offer.missions} {offer.profile} {offer.benefits}"
    )


def campaign_of(offer: Any) -> str:
    """Identify offer campaign (`job`, `alternance`, or `stage`)."""
    text_mod = hw_text()
    cfg = hw_profile().active_config()
    contract_f = text_mod.fold(offer.contract or "")
    title_f = text_mod.fold(offer.title or "")
    mode_f = text_mod.fold(offer.apply_mode or "")
    if contract_f in ("job_etudiant", "job", "student_job") or mode_f.endswith("_job"):
        return "job"
    combined = f"{offer.contract} {offer.title}"
    is_alt = has_alternance_marker(combined)
    if is_alt and "alternance" in cfg.contracts:
        return "alternance"
    has_stage_word = any(
        text_mod.has(f"{contract_f} {title_f}", tok)
        for tok in ("stage", "stagiaire", "intern", "internship")
    )
    if (
        (cfg.preset_id == "student_job_only" or tuple(cfg.contracts) == ("job",))
        and not has_stage_word
        and not is_alt
    ):
        return "job"
    if (
        "job" in cfg.contracts
        and not has_stage_word
        and not is_alt
        and (
            any(k in contract_f for k in ("cdd", "cdi", "interim", "temps partiel", "saisonnier"))
            or filters_mod().matches_job_title(offer.title or "")
        )
    ):
        return "job"
    if "alternance" in cfg.contracts and "stage" not in cfg.contracts and not has_stage_word:
        return "alternance"
    return "stage"


def is_eligible_for_plan(
    score: Score,
    apply_capability: str | None = None,
    *,
    campaign: str = "stage",
) -> bool:
    """Allow automatic queue selection from 60/100 for native HelloWork student jobs."""
    prof = hw_profile()
    if score.rejected or score.location_status == "unknown":
        return False
    if score.value >= prof.MIN_SCORE:
        return True
    if (
        str(apply_capability or "").strip() == "auto_hellowork"
        and score.value >= prof.AUTO_HELLOWORK_MIN_SCORE
    ):
        return campaign == "job"
    return False


def summary(offer: Any, score: Score) -> str:
    return (
        f"[{score.value:>3}/100] {offer.title} — {offer.company} "
        f"({offer.location_label}) · {hw_text().shorten(score.verdict, 40)}"
    )

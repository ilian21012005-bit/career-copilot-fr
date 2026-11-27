"""Filtres métier et distance réelle. Adzuna dépasse souvent le rayon demandé."""

from __future__ import annotations

import math
import re
import unicodedata

import candidate_config
import config
from config import (
    JOB_ALLOW_FULL_TIME,
    JOB_ALLOW_SEASONAL_FULL_TIME,
    JOB_WEEKDAY_PART_TIME,
    SENIOR_MARKERS,
)

JOB_MUST = (
    "polyvalent",
    "rayon",
    "caisse",
    "caissier",
    "caissiere",
    "équipier",
    "equipier",
    "vendeur",
    "vendeuse",
    "serveur",
    "serveuse",
    "restauration",
    "magasin",
    "accueil",
    "hôte",
    "hote",
    "hôtesse",
    "hotesse",
    "job étudiant",
    "job etudiant",
    "contrat étudiant",
    "contrat etudiant",
    "emploi étudiant",
    "emploi etudiant",
    "préparateur",
    "preparateur",
    "préparation de commandes",
    "preparation de commandes",
    "commandes",
    "logistique",
    "inventaire",
    "manutention",
    "manutentionnaire",
    "trieur",
    "agent de tri",
    "tri colis",
    "centre de tri",
    "colis",
    "entrepôt",
    "entrepot",
    "drive",
    "picking",
    "emballeur",
    "conditionnement",
    "noël",
    "noel",
    "saisonnier",
    "saisonniere",
    "renfort",
    "intérim",
    "interim",
    "intérimaire",
    "interimaire",
    "employé commercial",
    "employe commercial",
    "libre service",
    "conseiller de vente",
    "conseiller vente",
    "amazon",
    "ory4",
)

JOB_REJECT = (
    "alternance",
    "alternant",
    "apprentissage",
    "apprenti",
    "formation",
    "formateur",
    "bts",
    "boucher",
    "poissonnier",
    "charcutier",
    "pâtissier",
    "patissier",
    "boulanger",
    "cuisinier",
    "cap cuisine",
    "bep cuisine",
    "caces",
    "cariste",
    "poids lourd",
    "permis c",
    "spl",
    "chef de rayon",
    "responsable de rayon",
    "adjoint responsable",
    "responsable de caisse",
    "responsable caisse",
    "responsable magasin",
    "directeur",
    "opticien",
    "opticienne",
    "lunetier",
    "audioprothesiste",
    "preparateur en pharmacie",
    "pharmacie",
    "coiffeur",
    "coiffeuse",
    "estheticien",
    "estheticienne",
    "aide-soignant",
    "aide soignant",
    "infirmier",
    "infirmiere",
    "auxiliaire de puericulture",
)

FULL_TIME = (
    "35h",
    "35 h",
    "39h",
    "39 h",
    "40h",
    "temps plein",
    "temps complet",
)

PART_TIME_WEEKLY_HOURS = (
    "8h",
    "8 h",
    "10h",
    "10 h",
    "12h",
    "12 h",
    "14h",
    "14 h",
    "15h",
    "15 h",
    "16h",
    "16 h",
    "18h",
    "18 h",
    "20h",
    "20 h",
    "21h",
    "21 h",
    "22h",
    "22 h",
    "23h",
    "23 h",
    "24h",
    "24 h",
    "25h",
    "25 h",
    "26h",
    "26 h",
    "28h",
    "28 h",
)

PART_TIME_SIGNALS = (
    "temps partiel",
    "parttime",
    "part_time",
    "part-time",
    "mi-temps",
    "mi temps",
    "demi-journee",
    "matinee",
    "apres-midi",
    "week-end",
    "weekend",
    "samedi",
    "dimanche",
    "soir",
    "soiree",
    *PART_TIME_WEEKLY_HOURS,
)

# Périodes compatibles avec les vacances IUT : autorisées même à 35h/temps plein (hors CDI).
HOLIDAY_SEASONAL_SIGNALS = (
    "saisonnier",
    "saisonniere",
    "contrat saisonnier",
    "noel",
    "fetes",
    "fin d'annee",
    "vacances",
    "vacances scolaires",
    "vacances de noel",
    "vacances d'ete",
    "job d'ete",
    "job de noel",
)

STUDENT_JOB_TITLE_MARKERS = (
    "job etudiant",
    "contrat etudiant",
    "emploi etudiant",
    "etudiant",
    "etudiante",
)

OPERATIONAL_FOCUS_MARKERS = (
    "devops",
    "devsecops",
    "secops",
    "cyber",
    "securite",
    "security",
    "infrastructure",
    "infra",
    "cloud",
    "sre",
    "soc",
    "systeme",
    "systemes",
    "reseau",
    "network",
    "support",
    "exploitation",
    "production informatique",
    "itsm",
    "qualite",
    "qa",
    "test",
    "recette",
    "validation",
    "supervision",
    "observabilite",
    "hpc",
    "administration",
)

PURE_DEVELOPMENT_TITLES = (
    "developpeur logiciel",
    "software developer",
    "software engineer",
    "developpement logiciel",
    "software development",
    "developpeur informatique",
    "developpeur d'application",
    "developpeur fullstack",
    "developpeur full stack",
    "developpeur frontend",
    "developpeur front end",
    "developpeur backend",
    "developpeur back end",
    "developpeur web",
    "developpeur mobile",
    "developpement informatique",
    "developpement web",
    "developpement applicatif",
    "developpement mobile",
    "low-code",
    "low code",
    "data scientist",
    "machine learning engineer",
    "ingenieur machine learning",
)


def _fold(text: str) -> str:
    lowered = text.lower().replace("’", "'")
    normalized = unicodedata.normalize("NFD", lowered)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _active_profile() -> candidate_config.CandidateProfileConfig:
    return candidate_config.get_profile()


def _active_exclusions(cfg: candidate_config.CandidateProfileConfig) -> tuple[str, ...]:
    if not cfg.custom_exclude_keywords:
        return config.BASE_EXCLUSIONS
    return tuple(dict.fromkeys((*config.BASE_EXCLUSIONS, *cfg.custom_exclude_keywords)))


def _active_stage_must(cfg: candidate_config.CandidateProfileConfig) -> tuple[str, ...]:
    if not cfg.custom_stage_titles:
        return cfg.preset.stage_must
    return tuple(dict.fromkeys((*cfg.preset.stage_must, *cfg.custom_stage_titles)))


def _distance_limit(
    campaign: str, cfg: candidate_config.CandidateProfileConfig
) -> float:
    if campaign == "job":
        return float(cfg.job_radius_km)
    return max((float(z.get("km", 30.0)) for z in cfg.zones), default=30.0)


def _is_alternance_offer(target: dict, folded_title: str) -> bool:
    if target.get("alternance"):
        return True
    contract = _fold(str(target.get("contract") or ""))
    contract_type = _fold(str(target.get("contract_type") or ""))
    markers = ("alternan", "apprent", "professionnalisation", "contrat pro")
    if any(marker in val for val in (contract, contract_type) for marker in markers):
        return True
    return any(marker in folded_title for marker in markers)


def excluded(text: str) -> bool:
    folded = _fold(text)
    exclusions = _active_exclusions(_active_profile())
    return any(_fold(item) in folded for item in exclusions if item)


def _is_candidate_bac4_plus() -> bool:
    try:
        raw = _fold(str((_active_profile().candidate or {}).get("level") or ""))
    except Exception:
        return False
    return any(
        tok in raw
        for tok in (
            "bac+5",
            "bac +5",
            "bac+4",
            "bac +4",
            "master",
            "m1",
            "m2",
            "ingenieur",
            "pfe",
            "doctorat",
            "niveau 7",
        )
    )


def too_senior(text: str) -> bool:
    folded = _fold(text)
    if _is_candidate_bac4_plus():
        senior_only = (
            "senior",
            "lead ",
            "directeur",
            "chef de service",
            "5 ans d'experience",
            "10 ans d'experience",
            "doctorat",
            "phd",
        )
        return any(w in folded for w in senior_only)
    return any(_fold(word) in folded for word in SENIOR_MARKERS)


def stage_relevant(text: str, source: str) -> bool:
    src = (source or "").strip().lower()
    if src == "labonneboite":
        return True
    folded = _fold(text)
    must_words = _active_stage_must(_active_profile())
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(_fold(word)) + r"(?![a-z0-9])", folded)
        for word in must_words
        if word
    )


def _title(target: dict) -> str:
    return target.get("title") or target.get("text") or ""


def within_radius(target: dict, max_km: float) -> bool:
    source = str(target.get("source") or "").strip().lower()
    if source == "labonneboite":
        return True
    lat = (
        target.get("latitude")
        if target.get("latitude") is not None
        else target.get("lat")
    )
    lon = (
        target.get("longitude")
        if target.get("longitude") is not None
        else target.get("lon")
    )
    origin_lat = target.get("origin_lat")
    origin_lon = target.get("origin_lon")
    if source == "lba" and (lat is None or lon is None):
        return True
    if None in (lat, lon, origin_lat, origin_lon):
        return False
    return _km(origin_lat, origin_lon, lat, lon) <= max_km


def _has_bounded_token(folded_s: str, token: str) -> bool:
    return bool(
        re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", folded_s)
    )


def _strip_daily_hour_ranges(folded_s: str) -> str:
    return re.sub(
        r"(?<![a-z0-9])\d{1,2}\s*h(?:\d{2})?\s*(?:-|–|/|a|au|jusqu'a)\s*\d{1,2}\s*h(?:\d{2})?(?![a-z0-9])",
        " ",
        folded_s,
    )


def has_operational_focus(text: str) -> bool:
    folded = _fold(text)
    return any(_fold(marker) in folded for marker in OPERATIONAL_FOCUS_MARKERS)


def matches_job_title(title: str) -> bool:
    """Vérifie la cohérence du titre job étudiant sans ouvrir aux stages ni aux faux positifs."""
    folded_title = _fold(title)
    if not folded_title:
        return False
    if any(
        _has_bounded_token(folded_title, tok)
        for tok in ("stage", "stagiaire", "intern", "internship")
    ):
        return False
    if "alternan" in folded_title or "apprent" in folded_title:
        return False
    for word in JOB_MUST:
        folded_word = _fold(word)
        if folded_word == "hote":
            if re.search(r"(?<![a-z0-9])hotes?(?:se)?(?![a-z0-9])", folded_title):
                return True
            continue
        if len(folded_word) <= 6 and " " not in folded_word:
            if _has_bounded_token(folded_title, folded_word):
                return True
            continue
        if folded_word in folded_title:
            return True
    return any(
        _has_bounded_token(folded_title, sig) for sig in STUDENT_JOB_TITLE_MARKERS
    )


def job_candidate_ok(title: str, body: str = "", contract_type: str = "") -> bool:
    """Filtre déterministe pré-géocodage pour les jobs étudiants (politique IUT temps partiel/saisonnier)."""
    folded_title = _fold(title)
    folded_text = _fold(f"{title} {body}".strip())
    if excluded(f"{title} {body}") or too_senior(title):
        return False
    if any(_fold(word) in folded_title for word in JOB_REJECT):
        return False
    if _missing_required_cert(folded_text):
        return False
    target = {"title": title, "text": body, "contract_type": contract_type}
    if _incompatible_job_contract(target, folded_title, folded_text):
        return False
    return matches_job_title(title)


def keep(target: dict, campaign: str) -> bool:
    if campaign not in ("job", "stage", "alternance"):
        return False
    cfg = _active_profile()
    text = target.get("text") or ""
    title_raw = _title(target)
    title = _fold(title_raw)
    source = str(target.get("source") or "").strip().lower()
    limit = _distance_limit(campaign, cfg)
    is_alt = _is_alternance_offer(target, title)

    if excluded(f"{title_raw} {text}") or not within_radius(target, limit):
        return False

    if campaign == "job":
        if is_alt:
            return False
        return job_candidate_ok(
            title_raw,
            text,
            str(target.get("contract_type") or ""),
        )

    if campaign == "stage":
        if is_alt and not cfg.accepts_alternance:
            return False
        if source != "labonneboite":
            has_stage_marker = (
                "stage" in title
                or _has_bounded_token(title, "stagiaire")
                or _has_bounded_token(title, "intern")
                or _has_bounded_token(title, "internship")
            )
            if not has_stage_marker and not (cfg.accepts_alternance and is_alt):
                return False
    else:  # campaign == "alternance"
        if source not in ("lba", "labonneboite") and not is_alt:
            return False

    if (
        not cfg.allow_pure_software_dev
        and any(_fold(marker) in title for marker in PURE_DEVELOPMENT_TITLES)
        and not has_operational_focus(title)
    ):
        return False
    if too_senior(text):
        return False
    return stage_relevant(f"{title_raw} {text}".strip(), source)


def _missing_required_cert(folded_text: str) -> bool:
    if "sans caces" in folded_text or "caces non requis" in folded_text:
        pass
    elif any(
        marker in folded_text
        for marker in (
            "caces 3",
            "caces 1 3",
            "caces 1, 3",
            "caces 1/3",
            "caces r489",
            "caces r389",
        )
    ):
        return True
    return any(
        marker in folded_text
        for marker in (
            "cap cuisine",
            "bep cuisine",
            "cap boulanger",
            "cap patissier",
            "diplome d'opticien",
            "diplome opticien",
            "bts opticien",
            "opticien lunetier",
            "diplome d'etat",
            "cap petite enfance",
            "bp preparateur en pharmacie",
            "cap coiffure",
            "cap esthetique",
        )
    )


def _has_long_weekday_shift(folded_title: str, folded_text: str) -> bool:
    """Détecte les horaires de semaine incompatibles avec les cours IUT (ex: 6h-13h, lun-ven)."""
    combined = f"{folded_title} {folded_text}".strip()
    if re.search(r"\b(?:du\s+)?lundi\s+(?:au|a|-)\s+(?:vendredi|jeudi)\b", combined):
        return True
    for match in re.finditer(
        r"(?<![a-z0-9])(\d{1,2})\s*h(?:\s*(\d{2}))?\s*(?:-|–|a|au|jusqu'a)\s*(\d{1,2})\s*h(?:\s*(\d{2}))?(?![a-z0-9])",
        combined,
    ):
        start_h = int(match.group(1))
        start_m = int(match.group(2) or 0)
        end_h = int(match.group(3))
        end_m = int(match.group(4) or 0)
        if 5 <= start_h <= 12 and end_h <= 19:
            duration_min = (end_h * 60 + end_m) - (start_h * 60 + start_m)
            if duration_min >= 360:
                return True
    return False


def _incompatible_job_contract(
    target: dict, folded_title: str, folded_text: str
) -> bool:
    contract = _fold(str(target.get("contract_type") or ""))
    sanitized_title = _strip_daily_hour_ranges(folded_title)
    sanitized_text = _strip_daily_hour_ranges(folded_text)
    has_part_time = any(
        _has_bounded_token(hay, tok)
        for tok in PART_TIME_SIGNALS
        for hay in (sanitized_title, sanitized_text, contract)
    )
    has_holiday_seasonal = any(
        _has_bounded_token(hay, sig)
        for sig in HOLIDAY_SEASONAL_SIGNALS
        for hay in (folded_title, folded_text, contract)
    )
    has_student_marker = any(
        _has_bounded_token(folded_text, tok) for tok in ("etudiant", "etudiante")
    )
    explicit_full_title = any(
        _has_bounded_token(folded_title, _fold(word)) for word in FULL_TIME
    ) or (
        contract
        in {
            _fold(w) for w in ("full_time", "full-time", "temps plein", "temps complet")
        }
    )
    explicit_full_text = (not has_part_time) and any(
        _has_bounded_token(folded_text, _fold(word)) for word in FULL_TIME
    )
    is_full_time_hours = explicit_full_title or explicit_full_text

    is_permanent = (
        contract in {"permanent", "cdi"}
        or _has_bounded_token(folded_title, "cdi")
        or (_has_bounded_token(folded_text, "cdi") and not has_part_time)
    )
    if is_permanent:
        return is_full_time_hours or not has_part_time

    if (
        not JOB_ALLOW_FULL_TIME
        and not JOB_WEEKDAY_PART_TIME
        and not has_part_time
        and not (JOB_ALLOW_SEASONAL_FULL_TIME and has_holiday_seasonal)
        and not has_student_marker
        and _has_long_weekday_shift(folded_title, folded_text)
    ):
        return True

    if not is_full_time_hours:
        return False
    if JOB_ALLOW_FULL_TIME:
        return False
    if JOB_ALLOW_SEASONAL_FULL_TIME and has_holiday_seasonal:
        return False
    return True


def same_offer(campaign: str, name: str, title: str) -> str:
    raw = f"{campaign} {name} {title}"
    raw = re.sub(r"\([^)]{1,6}\)", " ", raw)
    raw = _fold(raw)
    raw = re.sub(r"\b(h/?f|f/?h)\b", " ", raw)
    raw = re.sub(r"[^a-z0-9 ]", " ", raw)
    return " ".join(raw.split())


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))

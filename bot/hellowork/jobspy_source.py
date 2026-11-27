"""Découverte multi-boards via JobSpy → store HelloWork.

JobSpy alimente la file ; le score profond + partner_deep décident du fit.
Aucun envoi automatique. Dry-run possible (`dry_run=True`).
"""

from __future__ import annotations

import hashlib
import math
import logging
import os
import re
import urllib.parse
from datetime import date, datetime

import filters
from filters import OPERATIONAL_FOCUS_MARKERS

from . import geo, offer as offers_mod, score as scoring, store
from .offer import Offer
from .text import fold

LOG = logging.getLogger("hellowork.jobspy_source")

QUERIES = (
    # Systèmes, réseaux et infrastructure
    "stage administration systèmes",
    "stage administrateur systèmes réseaux",
    "stage technicien systèmes réseaux",
    "stage infrastructure informatique",
    "stage support informatique",
    "stage helpdesk informatique",
    "stage technicien proximité informatique",
    "stage support applicatif informatique",
    "stage exploitation production informatique",
    "stage ITSM gestion incidents informatique",
    "stage gestion parc informatique MDM",
    "stage déploiement postes informatiques",
    # Cloud / DevOps
    "stage DevOps",
    "stage DevSecOps",
    "stage automatisation cloud",
    "stage CI/CD cloud",
    "stage ingénieur cloud sécurité",
    "stage infrastructure as code",
    "stage Kubernetes Docker",
    "stage AWS Azure DevOps",
    # Qualité / bases de données / gouvernance IT
    "stage QA test logiciel informatique",
    "stage qualité recette informatique",
    "stage test validation qualité informatique",
    "stage base de données SQL",
    "stage administration bases de données",
    "stage data analyst reporting informatique",
    "stage analyste fonctionnel système information",
    "stage gouvernance conformité audit système information",
    "stage gestion projet informatique SI",
    "stage infrastructure HPC Linux",
    "stage systèmes embarqués validation test",
    "stage informatique industrielle systèmes réseaux",
    "stage GRC cybersécurité",
    # Cybersécurité, dont SOC
    "stage analyste SOC",
    "stage SOC cybersécurité",
    "stage sécurité des systèmes d'information",
    "stage infrastructure réseau sécurité",
    "stage cybersécurité opérationnelle",
    "stage blue team",
    "stage supervision SIEM",
    "stage technicien réseau sécurité",
)

# Boards utiles en France pour un stage BUT 3 informatique.
SITES = ("indeed", "hellowork")  # linkedin en option (429 fréquent)

# Bassins stage uniquement ; job étudiant = Villebon et Saclay (15 km).
STAGE_LOCATIONS = (
    "Villebon-sur-Yvette 91",
    "Massy 91",
    "Palaiseau 91",
    "Mantes-la-Jolie 78",
    "Pessac 33",
    "Essonne",
    "Hauts-de-Seine",
    "Yvelines",
    "Gironde",
)

JOB_LOCATIONS = (
    "Villebon-sur-Yvette 91",
    "Massy 91",
    "Palaiseau 91",
    "Les Ulis 91",
    "Antony 92",
    "Essonne",
)

def _per_run(value: str, default: int, total: int) -> int:
    """Borne le nombre de bassins interrogés par exécution (rotation quotidienne)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, total))


def _rotated_locations(locations: tuple[str, ...], per_run: int) -> tuple[str, ...]:
    """Sélectionne une fenêtre glissante déterministe pour éviter ~450 appels/jour.

    Avec 3 bassins stage et 2 bassins job, chaque zone reste couverte tous les 3 jours
    environ, sans multiplier les requêtes par toutes les communes chaque matin.
    """
    if per_run >= len(locations):
        return locations
    start = date.today().toordinal() % len(locations)
    return tuple(locations[(start + offset) % len(locations)] for offset in range(per_run))


JOB_QUERIES = (
    "vendeur",
    "caissier",
    "employé polyvalent magasin",
    "hôte de caisse",
    "mise en rayon",
    "employé commercial",
    "employé libre service",
    "préparateur de commandes",
    "employé logistique",
    "équipier polyvalent",
    "job étudiant",
    "vendeur saisonnier noël",
)


def available() -> bool:
    if os.getenv("COMMERCIAL_SAFE", "").strip().lower() in {"1", "true", "yes", "on", "oui"}:
        return False
    if os.getenv("CAREER_EDITION", "").strip().lower() == "commercial":
        return False
    import importlib.util

    return importlib.util.find_spec("jobspy") is not None


def _offer_id(site: str, url: str, title: str, company: str) -> str:
    raw = f"{site}|{url}|{title}|{company}".encode("utf-8")
    return "js-" + hashlib.sha1(raw).hexdigest()[:16]


TARGET_KEEP = (
    "cyber", "soc", "siem", "securite", "sécurité", "reseau", "réseau", "reseaux",
    "infrastructure", "sysadmin", "administrateur systeme", "administrateur reseaux",
    "administrateur systemes", "pentest", "blue team", "red team", "edr",
    "active directory", "cloud sec", "forensic", "incident", "pare-feu", "firewall",
    "supervision", "technicien reseau", "technicien reseaux",
    "devops", "devsecops", "devsec", "ci/cd", "cicd", "kubernetes", "k8s",
    "docker", "ansible", "terraform", "gitlab ci", "jenkins", "aws", "azure",
    "cloud", "automatisation", "sre", "observabilite", "observabilité",
    "prometheus", "grafana",
    "support informatique", "support technique", "helpdesk", "technicien informatique",
    "qualite", "qualité", "test logiciel", "recette", "validation", "qa",
    "base de donnees", "base de données", "sql", "business intelligence",
    "itsm", "gestion des incidents", "gestion de parc", "mdm", "deploiement poste",
    "support applicatif", "support utilisateurs", "support utilisateur", "service desk",
    "administration de bases", "data analyst", "reporting", "analyse fonctionnelle",
    "systeme d'information", "systemes d'information", "système d'information",
    "systèmes d'information", "analyste fonctionnel", "gouvernance", "gestion de projet",
    "hpc", "calcul haute performance", "informatique industrielle", "systemes embarques",
    "systèmes embarqués", "informatique embarquée", "exploitation informatique",
    "virtualisation", "vmware", "proxmox", "linux", "windows server", "mco",
    "ebios", "grc", "iso 27001", "nis2", "audit informatique", "conformite", "conformité",
)
TARGET_DROP = (
    "community manager", "business developer", "commercial", "marketing",
    "communication", "rh ", "ressources humaines", "assistant administratif",
    "assistante administrative", "immobilier", "influence", "chef de projet influence",
    "fullstack", "full stack", "frontend", "front-end", "backend", "back-end",
    "data scientist", "machine learning engineer", "ingenieur machine learning",
    "data engineer", "webmaster", "web master",
    "controleur de gestion", "fpga", "methodes formelles",
    "cryptologie", "fondations", "baseband", "plm",
    "ios developer", "android developer", "administrateur 3d",
    "genie civil", "génie civil", "ouvrages d'art", "inspection d'ouvrages", "travaux publics",
)
DEVELOPMENT_ROLE_MARKERS = (
    "developpeur", "developer", "software engineer", "software development",
    "developpement logiciel",
)

def _is_stage(title: str, description: str, job_type) -> bool:
    blob = fold(f"{title} {description} {job_type}")
    title_f = fold(title)
    if any(x in blob for x in ("alternance", "apprentissage")) and "stage" not in title_f:
        return False
    if not ("stage" in blob or "internship" in blob or "intern" in title_f):
        return False
    if any(bad in title_f or bad in blob for bad in TARGET_DROP):
        return False
    if any(marker in title_f for marker in DEVELOPMENT_ROLE_MARKERS) and not any(
        marker in blob for marker in OPERATIONAL_FOCUS_MARKERS
    ):
        return False
    # Faux positif FPGA SoC
    if "fpga" in title_f and "soc" in title_f and "cyber" not in title_f:
        return False
    # Keep cyber/sys/network focus; otherwise skip early (score would be weak noise)
    if not any(k in blob for k in TARGET_KEEP):
        return False
    # Soft Bac+5 : on laisse passer (le score plafonne). On drop seulement
    # les annonces 100% école d'ingé / Master 2 sans ouverture Bac+3.
    bac3_ok = any(
        m in blob
        for m in ("bac+3", "bac +3", "but 3", "but3", "licence", "bac+2", "bachelor")
    )
    exclusive = (
        any(m in blob for m in ("bac+5 exig", "master 2 exig", "master2 exig", "bac +5 exig"))
        or (
            ("ecole d'ingenieur" in blob or "ecole d ingenieurs" in blob)
            and ("bac+5" in blob or "master 2" in blob)
            and not bac3_ok
        )
    )
    if exclusive:
        return False
    return True


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        # pandas NaN
        if isinstance(value, float) and math.isnan(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def _is_student_job(title: str, description: str, job_type) -> bool:
    blob = fold(f"{title} {description} {job_type}")
    title_f = fold(title)
    if any(x in blob for x in ("alternance", "apprentissage")) and "etudiant" not in title_f:
        return False
    target = {
        "title": title,
        "text": f"{title} {description}",
        "contract_type": job_type or "",
        "source": "hellowork",
    }
    if filters.excluded(target["text"]) or any(fold(w) in title_f for w in filters.JOB_REJECT):
        return False
    if filters._missing_required_cert(blob) or filters._incompatible_job_contract(target, title_f, blob):
        return False
    return any(fold(w) in title_f for w in (*filters.JOB_MUST, "job etudiant", "etudiant"))


def _row_to_offer(row: dict, *, campaign: str = "stage") -> Offer | None:
    title = _clean(row.get("title"))
    company = _clean(row.get("company")) or "Entreprise"
    site = (_clean(row.get("site")) or "jobspy").lower()
    job_url = _clean(row.get("job_url"))
    direct_url = _clean(row.get("job_url_direct"))
    # Sur HelloWork, garder l'URL canonique hellowork.com pour préserver le tunnel natif.
    if site == "hellowork" and "hellowork.com" in job_url.lower():
        url = job_url
    else:
        url = direct_url or job_url
    description = _clean(row.get("description"))
    location = row.get("location")
    city = ""
    department = ""
    if location is not None and _clean(location):
        city = _clean(getattr(location, "city", None)) or _clean(location)
        department = _clean(getattr(location, "state", None))
        if hasattr(location, "display") and not city:
            city = _clean(getattr(location, "display", None))
    city = re.sub(r"\s+", " ", city).strip()
    if city:
        m_dep = re.search(r",\s*(\d{2,3}|2[AB])(?:\s*,\s*France)?\s*$", city, re.I)
        if m_dep:
            department = department or m_dep.group(1)
            city = city[: m_dep.start()].strip()
        city = re.sub(r",\s*France\s*$", "", city, flags=re.I).strip()
    job_type = row.get("job_type") or ""
    if isinstance(job_type, (list, tuple)):
        job_type = " ".join(_clean(x) for x in job_type if _clean(x))
    else:
        job_type = _clean(job_type)

    if not title or not url:
        return None
    is_job = campaign == "job"
    if is_job:
        if not _is_student_job(title, description, job_type):
            return None
    elif not _is_stage(title, description, job_type):
        return None
    parsed_url = urllib.parse.urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.hostname or parsed_url.username or parsed_url.password:
        return None
    try:
        import public_network

        public_network.target(url)
    except (ImportError, ValueError):
        return None

    url = offers_mod.canonical(url) if offers_mod.is_offer_page(url) else url
    oid = offers_mod.offer_id(url) if offers_mod.is_offer_page(url) else _offer_id(site, url, title, company)
    contract = "job_etudiant" if is_job else "stage"
    offer_title = title if (is_job or "stage" in fold(title)) else f"Stage - {title}"
    return Offer(
        id=oid,
        url=url,
        title=offer_title,
        company=company,
        city=city,
        department=department,
        contract=contract,
        posted_at=str(row.get("date_posted") or ""),
        salary="",
        missions="",
        profile="",
        benefits="",
        description=description,
        apply_mode=f"jobspy_{site}_job" if is_job else f"jobspy_{site}",
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def scrape_batch(
    *,
    location: str | None = None,
    locations: tuple[str, ...] | None = None,
    results_wanted: int = 12,
    hours_old: int = 72,
    sites: tuple[str, ...] = SITES,
    queries: tuple[str, ...] | None = None,
    dry_run: bool = False,
    campaign: str = "stage",
) -> dict:
    """Lance JobSpy sur les bassins ciblés (stage ou job_etudiant), filtre, enregistre."""
    if not available():
        return {"ok": False, "error": "python-jobspy non installé", "added": 0}

    results_wanted = max(1, min(int(results_wanted), 25))
    hours_old = max(1, min(int(hours_old), 720))
    is_job = campaign == "job"

    from jobspy import scrape_jobs

    store.init()
    seen_urls: set[str] = set()
    added = 0
    kept = 0
    rejected = 0
    errors: list[str] = []
    samples: list[dict] = []
    if queries is None:
        queries = JOB_QUERIES if is_job else QUERIES
    if locations is None:
        if location:
            locations = (location,)
        else:
            pool = JOB_LOCATIONS if is_job else STAGE_LOCATIONS
            if is_job:
                per_run = _per_run(
                    os.getenv("JOBSPY_JOB_LOCATIONS_PER_RUN", "2"), 2, len(pool)
                )
            else:
                per_run = _per_run(
                    os.getenv("JOBSPY_STAGE_LOCATIONS_PER_RUN", "3"), 3, len(pool)
                )
            locations = _rotated_locations(pool, per_run)

    for location_name in locations:
        LOG.info("JobSpy bassin %s %s", campaign, location_name)
        for query in queries:
            try:
                scrape_kwargs = {
                    "site_name": list(sites),
                    "search_term": query,
                    "location": location_name,
                    "distance": 10 if is_job else 18,
                    "results_wanted": results_wanted,
                    "hours_old": hours_old,
                    "country_indeed": "France",
                    "description_format": "plain",
                    "fetch_description": True,
                    "verbose": 0,
                }
                if not is_job:
                    scrape_kwargs["job_type"] = "internship"
                df = scrape_jobs(**scrape_kwargs)
            except Exception as exc:
                LOG.warning("JobSpy %s / %r : %s", location_name, query, exc)
                errors.append(f"{location_name}|{query}: {exc}")
                continue

            if df is None or getattr(df, "empty", True):
                continue

            records = df.to_dict(orient="records")
            for row in records:
                offer = _row_to_offer(row, campaign=campaign)
                if offer is None:
                    continue
                if offer.url in seen_urls:
                    continue
                seen_urls.add(offer.url)
                kept += 1
                if dry_run:
                    samples.append(
                        {
                            "id": offer.id,
                            "title": offer.title,
                            "company": offer.company,
                            "city": offer.city,
                            "url": offer.url,
                            "mode": offer.apply_mode,
                            "search_location": location_name,
                        }
                    )
                    continue

                try:
                    geo.resolve(offer)
                except Exception:
                    pass
                result = scoring.evaluate(offer)
                previous = store.get(offer.id)
                existed = previous is not None
                store.save_offer(offer, result)
                if result.rejected:
                    if previous is None or previous["status"] in ("new", "shortlist", "prepared", "ignored"):
                        store.set_status(offer.id, "ignored")
                    rejected += 1
                elif not existed:
                    added += 1
                samples.append(
                    {
                        "id": offer.id,
                        "title": offer.title,
                        "company": offer.company,
                        "score": result.value,
                        "rejected": result.rejected,
                        "mode": offer.apply_mode,
                        "zone": offer.zone,
                        "search_location": location_name,
                    }
                )

    return {
        "ok": True,
        "dry_run": dry_run,
        "queries": list(queries),
        "sites": list(sites),
        "locations": list(locations),
        "unique_stage_like": kept,
        "added": added,
        "rejected": rejected,
        "errors": errors,
        "samples": samples[:40],
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

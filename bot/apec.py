"""Scraper d'annonces APEC (Association Pour l'Emploi des Cadres) via Playwright et webservice interne."""
from __future__ import annotations

import logging
import time
from typing import Any

from filters import _fold, _km

logger = logging.getLogger(__name__)

APEC_SEARCH_PAGE = "https://www.apec.fr/candidat/recherche-emploi.html/emploi"
APEC_WEBSERVICE = "https://www.apec.fr/cms/webservices/rechercheOffre"
CONTRAT_STAGE_CODE = "597171"  # Code APEC officiel pour les stages

STAGE_QUERIES = (
    "administration systèmes réseaux",
    "infrastructure informatique",
    "support informatique",
    "cloud DevOps",
    "qualité tests informatique",
    "bases de données SQL",
    "gouvernance cybersécurité",
    "cybersecurite",
    "reseaux",
    "securite informatique",
    "pentest",
    "soc",
)


def enabled(env: dict[str, str] | None = None) -> bool:
    """APEC est désactivé en mode commercial (CGU) et requiert Playwright en mode local."""
    import os

    cfg = env or {}
    comm = str(cfg.get("COMMERCIAL_SAFE") or os.getenv("COMMERCIAL_SAFE", "0")).strip().lower()
    edition = str(cfg.get("CAREER_EDITION") or os.getenv("CAREER_EDITION", "")).strip().lower()
    if comm in {"1", "true", "yes", "on", "oui"} or edition == "commercial":
        return False
    if str(cfg.get("APEC_ENABLED", os.getenv("APEC_ENABLED", "1"))).strip().lower() in {"0", "false", "no", "non"}:
        return False
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def normalize(item: dict[str, Any]) -> dict[str, Any] | None:
    """Convertit une annonce brute APEC au format standard du bot."""
    num = str(item.get("numeroOffre") or item.get("id") or "").strip()
    raw_title = (item.get("intitule") or "").strip()
    if not raw_title or not num:
        return None

    # Normalisation du titre : préfixer par "Stage - " si absent pour validation par filters.keep()
    title = raw_title if "stage" in _fold(raw_title) else f"Stage - {raw_title}"

    company = (item.get("nomCommercial") or "Entreprise").strip()
    city = (item.get("lieuTexte") or "").strip()
    url = f"https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/{num}"

    lat = None
    lon = None
    try:
        if item.get("latitude"):
            lat = float(item["latitude"])
        if item.get("longitude"):
            lon = float(item["longitude"])
    except (ValueError, TypeError):
        pass

    texte = (item.get("texteOffre") or "").strip()
    salaire = (item.get("salaireTexte") or "").strip()
    desc_parts = []
    if texte:
        desc_parts.append(texte)
    if salaire:
        desc_parts.append(f"\nGratification / Salaire : {salaire}")
    description = "\n".join(desc_parts)

    full_text = f"{title} {texte} {salaire} {city}"
    published_at = item.get("datePublication") or item.get("dateValidation") or ""

    return {
        "id": f"apec_{num}",
        "url": url,
        "email": "",
        "title": title,
        "name": company,
        "city": city,
        "latitude": lat,
        "longitude": lon,
        "text": full_text,
        "description": description,
        "source": "apec",
        "contract_type": "stage",
        "campaign": "stage",
        "published_at": published_at,
        "notes": f"APEC - {city} (Offre {num})",
    }


def search_all_keywords(queries: list[str] | tuple[str, ...], max_per_query: int = 50) -> list[dict[str, Any]]:
    """Ouvre une session Playwright furtive et exécute les requêtes de recherche via le webservice APEC."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright n'est pas installé dans l'environnement.")
        return []

    results: list[dict[str, Any]] = []
    seen_nums: set[str] = set()

    try:
        with sync_playwright() as p:
            launch_args: list[str] = []
            browser = None
            try:
                browser = p.chromium.launch(headless=True, channel="chrome", args=launch_args)
            except Exception:
                # Fallback sur Chromium standard si channel="chrome" non disponible
                browser = p.chromium.launch(headless=True, args=launch_args)

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                timezone_id="Europe/Paris",
            )
            page = context.new_page()

            # Charger la page d'accueil de recherche pour initialiser la session / cookies
            page.goto(APEC_SEARCH_PAGE, wait_until="networkidle", timeout=25000)

            # Exécuter les requêtes en JavaScript directement dans le contexte du navigateur
            js_script = """
            async (args) => {
                const { queries, maxPerQuery, contractCode, endpoint } = args;
                let items = [];
                for (const q of queries) {
                    const payload = {
                        niveauxEtude: null,
                        lieux: [],
                        dureesContrat: null,
                        fonctions: [],
                        statutPoste: [],
                        typesContrat: [contractCode],
                        typesConvention: null,
                        niveauxExperience: [],
                        secteursActivite: [],
                        typesTeletravail: [],
                        typeClient: 'CADRE',
                        sorts: [{ type: 'SCORE', direction: 'DESCENDING' }],
                        pagination: { range: maxPerQuery, startIndex: 0 },
                        activeFiltre: true,
                        pointGeolocDeReference: { distance: 0 },
                        inclureOP: false,
                        motsCles: q
                    };
                    try {
                        const resp = await fetch(endpoint, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        const data = await resp.json();
                        if (data && data.resultats) {
                            items.push(...data.resultats);
                        }
                    } catch (e) {}
                }
                return items;
            }
            """
            raw_items = page.evaluate(
                js_script,
                {
                    "queries": list(queries),
                    "maxPerQuery": max_per_query,
                    "contractCode": CONTRAT_STAGE_CODE,
                    "endpoint": APEC_WEBSERVICE,
                },
            )

            browser.close()

            for item in raw_items or []:
                num = str(item.get("numeroOffre") or item.get("id") or "")
                if num and num not in seen_nums:
                    seen_nums.add(num)
                    normalized = normalize(item)
                    if normalized:
                        results.append(normalized)

    except Exception as exc:
        logger.warning("Erreur lors du scraping APEC (%s)", type(exc).__name__)
        return []

    return results


# Cache mémoire pour éviter de relancer Playwright plusieurs fois dans le même cycle
_APEC_CACHE: dict[str, Any] = {"timestamp": 0.0, "offers": []}
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_cached_offers(queries: list[str] | tuple[str, ...] = STAGE_QUERIES) -> list[dict[str, Any]]:
    """Renvoie les offres APEC en cache ou les rafraîchit si expirées."""
    now = time.time()
    if _APEC_CACHE["offers"] and (now - _APEC_CACHE["timestamp"]) < CACHE_TTL_SECONDS:
        return _APEC_CACHE["offers"]

    offers = search_all_keywords(queries)
    _APEC_CACHE["offers"] = offers
    _APEC_CACHE["timestamp"] = now
    return offers


def search(zone: dict[str, Any], queries: list[str] | tuple[str, ...] = STAGE_QUERIES) -> list[dict[str, Any]]:
    """Renvoie les offres de stage APEC situées dans le rayon géographique de la zone demandée."""
    all_offers = get_cached_offers(queries)
    target_lat = zone.get("lat")
    target_lon = zone.get("lon")
    max_km = float(zone.get("km", 35))

    if target_lat is None or target_lon is None:
        return all_offers

    matched: list[dict[str, Any]] = []
    for offer in all_offers:
        lat = offer.get("latitude")
        lon = offer.get("longitude")
        if lat is not None and lon is not None:
            dist = _km(target_lat, target_lon, lat, lon)
            if dist <= max_km:
                matched_offer = dict(offer)
                matched_offer["km"] = round(dist, 1)
                matched.append(matched_offer)
        else:
            # Si pas de coordonnées, laisser filters.keep décider ou tenter par département
            matched.append(offer)

    return matched

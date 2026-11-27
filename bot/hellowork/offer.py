"""Lecture d'une fiche d'offre HelloWork, une page à la fois.

Ce module ne parcourt pas les pages de recherche : le robots.txt de HelloWork
interdit ``/fr-fr/emploi/recherche.html`` et tous les motifs contenant ``?``.
Il ne lit que les fiches que l'utilisateur désigne explicitement : URL collée,
lien reçu dans une alerte mail, ou URL extraite d'un fichier HAR.

Une seule requête par fiche, mise en cache locale, jamais de parallélisme.
Aucun contournement de blocage : un 403/429 remonte une erreur claire.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import time
import urllib.error
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from lxml import etree, html as LH

from config import DATA_DIR
import public_network
from private_storage import ensure_private_directory, write_private_text

from .text import clean_lines, fold

PAGES_DIR = DATA_DIR / "hellowork" / "pages"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
OFFER_URL = re.compile(r"^https?://(?:www\.)?hellowork\.com/fr-fr/emplois/(\d+)\.html")
MIN_DELAY = 3.0
CACHE_DAYS = 7
TRANSIENT_HTTP_STATUSES = frozenset({429, *range(500, 600)})

_last_fetch = 0.0

CONTRACT_WORDS = ("stage", "alternance", "apprentissage", "cdi", "cdd", "intérim", "interim", "freelance")

SECTION_KEYS = (
    ("description", ("detail du poste", "detail de l'offre", "description du poste", "descriptif")),
    ("missions", ("mission",)),
    ("profile", ("profil",)),
    ("benefits", ("avantage",)),
    ("steps", ("etape", "recrutement")),
)

BLOCK_TAGS = {"p", "li", "br", "div", "h1", "h2", "h3", "h4", "tr", "section", "ul", "ol"}


class FetchError(RuntimeError):
    """La fiche n'a pas pu être lue (réseau, refus, URL invalide)."""


@dataclass
class Offer:
    id: str
    url: str
    title: str
    company: str
    city: str = ""
    department: str = ""
    contract: str = ""
    posted_at: str = ""
    salary: str = ""
    missions: str = ""
    profile: str = ""
    benefits: str = ""
    description: str = ""
    apply_mode: str = "hellowork"
    fetched_at: str = ""
    latitude: float | None = None
    longitude: float | None = None
    zone: str = ""
    distance_km: float | None = None
    location_status: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "company": self.company,
            "city": self.city,
            "department": self.department,
            "contract": self.contract,
            "posted_at": self.posted_at,
            "salary": self.salary,
            "missions": self.missions,
            "profile": self.profile,
            "benefits": self.benefits,
            "description": self.description,
            "apply_mode": self.apply_mode,
            "fetched_at": self.fetched_at,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "zone": self.zone,
            "distance_km": self.distance_km,
            "location_status": self.location_status,
        }

    @property
    def location(self) -> str:
        if self.city and self.department:
            return f"{self.city} ({self.department})"
        return self.city or self.department or "lieu non précisé"

    @property
    def location_label(self) -> str:
        """« Massy · Villebon-sur-Yvette · 12,4 km » pour l'affichage."""
        parts = [self.city or self.department or "lieu inconnu"]
        if self.zone and self.distance_km is not None:
            parts.append(self.zone)
            parts.append(f"{self.distance_km:.0f} km")
        elif self.location_status == "unknown":
            parts.append("à vérifier")
        return " · ".join(parts)

    @property
    def posted_days(self) -> int | None:
        if not self.posted_at:
            return None
        try:
            posted = date.fromisoformat(self.posted_at[:10])
        except ValueError:
            return None
        return max(0, (date.today() - posted).days)


def offer_id(url: str) -> str:
    match = OFFER_URL.match((url or "").strip())
    if match:
        return match.group(1)
    return "h" + hashlib.sha1((url or "").strip().encode("utf-8")).hexdigest()[:12]


def is_offer_page(url: str) -> bool:
    return OFFER_URL.match((url or "").strip()) is not None


def canonical(url: str) -> str:
    parsed = urllib.parse.urlparse((url or "").strip())
    if parsed.netloc.endswith("hellowork.com") and parsed.path.startswith("/fr-fr/emplois/"):
        return f"https://www.hellowork.com{parsed.path}"
    return (url or "").strip()


def fetch_html(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    max_attempts: int = 3,
    backoff_s: float = 0.5,
    sleep: Callable[[float], None] | None = None,
) -> str:
    """Télécharge le HTML d'une fiche publique avec retry borné sur erreurs transitoires."""
    sleep_fn = sleep or time.sleep
    req_headers = headers or {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    attempts = max(1, int(max_attempts))
    last_status: int | None = None
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            status, raw = public_network.fetch(
                url,
                headers=req_headers,
                timeout=timeout,
                max_bytes=8 * 1024 * 1024,
            )
            if status in TRANSIENT_HTTP_STATUSES:
                last_status = status
                if attempt >= attempts:
                    raise FetchError(
                        f"HelloWork a répondu {status} pour cette fiche. "
                        "Le bot ne force pas le passage : réessaie plus tard ou ouvre la page à la main."
                    )
            elif status >= 400:
                raise FetchError(
                    f"HelloWork a répondu {status} pour cette fiche. "
                    "Le bot ne force pas le passage : réessaie plus tard ou ouvre la page à la main."
                )
            else:
                return _decode(raw, "")
        except FetchError:
            raise
        except urllib.error.HTTPError as exc:
            if exc.code not in TRANSIENT_HTTP_STATUSES or attempt >= attempts:
                raise FetchError(
                    f"HelloWork a répondu {exc.code} pour cette fiche. "
                    "Le bot ne force pas le passage : réessaie plus tard ou ouvre la page à la main."
                ) from exc
            last_exc = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt >= attempts:
                raise FetchError(f"Réseau indisponible ou destination refusée : {exc}") from exc
        except (public_network.NetworkPolicyError, http.client.HTTPException, OSError, ValueError) as exc:
            raise FetchError(f"Réseau indisponible ou destination refusée : {exc}") from exc
        if backoff_s > 0:
            sleep_fn(min(backoff_s * attempt, 5.0))
    if last_status is not None:
        raise FetchError(
            f"HelloWork a répondu {last_status} pour cette fiche. "
            "Le bot ne force pas le passage : réessaie plus tard ou ouvre la page à la main."
        )
    raise FetchError(f"Réseau indisponible ou destination refusée : {last_exc}")


def fetch(url: str, force: bool = False) -> tuple[str, Path]:
    """Télécharge la fiche (ou la relit du cache) et renvoie son HTML."""
    url = canonical(url)
    if not is_offer_page(url):
        raise FetchError(
            "URL refusée : ce n'est pas une fiche HelloWork "
            "(https://www.hellowork.com/fr-fr/emplois/<numéro>.html attendu)."
        )
    ensure_private_directory(PAGES_DIR)
    page = PAGES_DIR / f"{offer_id(url)}.html"
    if page.is_symlink():
        raise FetchError("Cache de fiche symbolique refusé.")
    if page.exists() and not force and _fresh(page):
        return page.read_text(encoding="utf-8", errors="replace"), page

    global _last_fetch
    wait = MIN_DELAY - (time.monotonic() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    try:
        text = fetch_html(url, headers=headers)
    finally:
        _last_fetch = time.monotonic()

    write_private_text(page, text)
    return text, page


def read(target: str, force: bool = False) -> Offer:
    """Lit une fiche depuis une URL HelloWork ou depuis un fichier HTML local."""
    target = (target or "").strip()
    if target.startswith("http"):
        raw, _ = fetch(target, force=force)
        return parse(raw, canonical(target))
    path = Path(target)
    if not path.exists():
        raise FetchError(f"Fichier introuvable : {target}")
    return parse(path.read_text(encoding="utf-8", errors="replace"), "")


def from_row(row) -> Offer:
    """Reconstruit une offre depuis une ligne SQLite (sans réaccès réseau)."""
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return Offer(
        id=row["id"],
        url=row["url"] or "",
        title=row["title"] or "",
        company=row["company"] or "",
        city=row["city"] or "",
        department=row["department"] or "",
        contract=row["contract"] or "",
        posted_at=row["posted_at"] or "",
        salary=row["salary"] or "",
        missions=row["missions"] or "",
        profile=row["profile"] or "",
        benefits=row["benefits"] or "",
        description=row["description"] or "",
        apply_mode=row["apply_mode"] or "hellowork",
        latitude=row["latitude"] if "latitude" in keys else None,
        longitude=row["longitude"] if "longitude" in keys else None,
        zone=row["zone"] if "zone" in keys and row["zone"] else "",
        distance_km=row["distance_km"] if "distance_km" in keys else None,
        location_status=(
            row["location_status"]
            if "location_status" in keys and row["location_status"]
            else "unknown"
        ),
    )


def parse(raw: str, url: str = "") -> Offer:
    doc = LH.fromstring(raw or "<html></html>")

    title = _text(doc.xpath("//*[@data-cy='jobTitle']")) or _text(doc.xpath("//h1"))
    company = _text(doc.xpath("//h1//a[contains(@href,'/fr-fr/entreprises/')]"))
    if not company:
        company = _company_from_og(doc)
    if not title:
        title = _company_from_og(doc) or "Offre sans titre"

    city, department, contract = _header_facts(doc, title)

    sections: dict[str, str] = {}
    for heading in doc.xpath("//h2"):
        label = fold(_text(heading))
        for key, needles in SECTION_KEYS:
            if key in sections:
                continue
            if any(needle in label for needle in needles):
                body = _section_text(heading)
                if body:
                    sections[key] = body
                break

    detail = sections.get("description", "")
    missions = sections.get("missions", "") or detail
    profile_text = sections.get("profile", "")
    benefits = sections.get("benefits", "")
    parts = [part for part in (detail, missions) if part]
    joined = "\n\n".join(parts)
    for part in (profile_text, benefits):
        if part and part not in joined:
            parts.append(part)
    description = "\n\n".join(parts)
    posted_at = _posted_at(doc)
    salary = _salary(doc)

    return Offer(
        id=offer_id(url) if url else "h" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12],
        url=canonical(url),
        title=_one_line(title),
        company=_one_line(company),
        city=city,
        department=department,
        contract=contract,
        posted_at=posted_at,
        salary=salary,
        missions=missions,
        profile=profile_text,
        benefits=benefits,
        description=description,
        apply_mode="hellowork",
        fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )


def _fresh(page: Path) -> bool:
    age = time.time() - page.stat().st_mtime
    return age < CACHE_DAYS * 86400


def _decode(raw: bytes, charset: str) -> str:
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            pass
    match = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4000], re.I)
    if match:
        try:
            return raw.decode(match.group(1).decode("ascii"), errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    return raw.decode("utf-8", errors="replace")


def _text(nodes) -> str:
    """Texte d'un élément, ou du premier élément d'une liste XPath."""
    if nodes is None:
        return ""
    if isinstance(nodes, (list, tuple)):
        if len(nodes) == 0:
            return ""
        node = nodes[0]
    else:
        node = nodes
    if not hasattr(node, "text_content"):
        return re.sub(r"\s+", " ", str(node)).strip()
    return re.sub(r"\s+", " ", node.text_content()).strip()


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _company_from_og(doc) -> str:
    for node in doc.xpath("//meta[@property='og:title']/@content | //meta[@name='og:title']/@content"):
        match = re.search(r"Recrutement par (.+?)\s*\|\s*Hellowork", node)
        if match:
            return match.group(1).strip()
    return ""


def _header_facts(doc, title: str) -> tuple[str, str, str]:
    """Ville, département et contrat depuis la liste sous le titre."""
    city = department = contract = ""
    h1 = doc.xpath("//h1")
    items: list[str] = []
    if h1:
        for li in h1[0].getparent().xpath(".//ul[1]/li"):
            label = _one_line(li.text_content())
            if label:
                items.append(label)
    for label in items:
        folded = fold(label)
        found = next((word for word in CONTRACT_WORDS if word in folded), "")
        if found and not contract:
            contract = found
            continue
        if re.search(r"\d{2,3}\s*$", label) and not city:
            city = re.sub(r"\s*[-–]\s*\d{2,3}\s*$", "", label).strip()
            department = (re.search(r"(\d{2,3})\s*$", label) or [None, ""])[1]
            continue
        if not city:
            city = label
    if not contract:
        folded_title = fold(title)
        contract = next((word for word in CONTRACT_WORDS if word in folded_title), "")
    return city, department, contract


def _section_text(heading) -> str:
    block = heading
    while block is not None and block.tag not in ("section", "details"):
        block = block.getparent()
    if block is None:
        block = heading.getparent()
    if block is None:
        return ""
    # On repart d'une copie sérialisée : modifier l'arbre d'origine effacerait
    # les titres des sections suivantes.
    clone = LH.fragment_fromstring(etree.tostring(block), create_parent=False)
    for node in clone.xpath(".//h2 | .//summary"):
        node.drop_tree()
    return _block_text(clone)


def _block_text(root) -> str:
    parts: list[str] = []
    for node in root.iter():
        tag = node.tag.lower() if isinstance(node.tag, str) else ""
        if tag in BLOCK_TAGS:
            parts.append("\n")
        if node.text:
            parts.append(node.text)
        if node.tail:
            parts.append(node.tail)
    return "\n".join(clean_lines("".join(parts)))


def _posted_at(doc) -> str:
    for value in doc.xpath("//time/@datetime"):
        match = re.match(r"(\d{4}-\d{2}-\d{2})", value or "")
        if match:
            return match.group(1)
    text = _one_line(" ".join(doc.xpath("//*[@id='offer-panel']//text()")))
    match = re.search(r"il y a (\d+)\s*jour", text, re.I)
    if match:
        return (date.today() - timedelta(days=int(match.group(1)))).isoformat()
    return ""


def _salary(doc) -> str:
    nodes = doc.xpath("//*[@data-cy='salary-tag-button']")
    if len(nodes) == 0:
        return ""
    text = _one_line(nodes[0].text_content())
    return "" if fold(text).startswith("pas de salaire") else text

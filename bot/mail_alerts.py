"""Collecte en lecture seule des alertes emploi/stage reçues sur Gmail.

Sources couvertes sans jamais scraper derrière un login :
- Jobteaser (alertes IUT / Paris-Saclay)
- Free-Work
- Meteojob
- StudentJob
- Campus Cyber
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import ssl
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlparse

from lxml import etree, html as LH

import application_contact
import filters
import source_common

LOG = logging.getLogger("mail_alerts")
IMAP_HOST = "imap.gmail.com"

_PORTAL_EMAIL_DOMAINS = frozenset(
    {
        "linkedin.com",
        "indeed.com",
        "welcometothejungle.com",
        "jobteaser.com",
        "free-work.com",
        "meteojob.com",
        "studentjob.fr",
        "studentjob.com",
        "campuscyber.fr",
        "campus-cyber.fr",
        "hellowork.com",
    }
)

PROVIDERS: dict[str, dict[str, Any]] = {
    "jobteaser": {
        "source": "mail-jobteaser",
        "sender_tokens": ("jobteaser.com",),
        "domains": ("jobteaser.com",),
        "default_campaign": "stage",
        "url_hints": ("/job-offers/", "/offres/", "/offer/", "/jobs/"),
    },
    "freework": {
        "source": "mail-freework",
        "sender_tokens": ("free-work.com",),
        "domains": ("free-work.com",),
        "default_campaign": "stage",
        "url_hints": ("/emplois/", "/jobs/", "/job/", "/offre/"),
    },
    "meteojob": {
        "source": "mail-meteojob",
        "sender_tokens": ("meteojob.com",),
        "domains": ("meteojob.com",),
        "default_campaign": "stage",
        "url_hints": ("/emploi/", "/offre/", "/offres/", "/jobs/"),
    },
    "studentjob": {
        "source": "mail-studentjob",
        "sender_tokens": ("studentjob.fr", "studentjob.com"),
        "domains": ("studentjob.fr", "studentjob.com"),
        "default_campaign": "job",
        "url_hints": ("/job", "/emploi", "/offre", "/vacature", "/stage"),
    },
    "campuscyber": {
        "source": "mail-campuscyber",
        "sender_tokens": ("campuscyber.fr", "campus-cyber"),
        "domains": ("campuscyber.fr", "talent.campuscyber.fr", "campus-cyber.fr"),
        "default_campaign": "stage",
        "url_hints": ("/offre", "/job", "/stage", "/recrutement", "/career"),
    },
    "linkedin": {
        "source": "mail-linkedin",
        "sender_tokens": ("jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com", "linkedin.com"),
        "domains": ("linkedin.com",),
        "default_campaign": "stage",
        "url_hints": ("/jobs/view/", "/comm/jobs/view/"),
    },
    "indeed": {
        "source": "mail-indeed",
        "sender_tokens": ("alert@indeed.com", "jobalerts.indeed.com", "indeed.com"),
        "domains": ("indeed.com", "fr.indeed.com"),
        "default_campaign": "stage",
        "url_hints": ("/viewjob", "/rc/clk", "/pagead/clk"),
    },
    "wttj": {
        "source": "mail-wttj",
        "sender_tokens": ("welcometothejungle.com",),
        "domains": ("welcometothejungle.com",),
        "default_campaign": "stage",
        "url_hints": ("/jobs/",),
    },
}

_SKIP_URL_TOKENS = (
    "unsubscribe",
    "desinscri",
    "optout",
    "privacy",
    "confidentialite",
    "mentions-legales",
    "cgu",
    "login",
    "signin",
    "signup",
    "settings",
    "preferences",
    "profil",
    "profile",
    "help",
)
_KNOWN_FR_CITIES_RE = re.compile(
    r"\b(Paris|Saclay|Orsay|Massy|Palaiseau|Villebon(?:-sur-Yvette)?|Vélizy(?:-Villacoublay)?|"
    r"Les\s+Ulis|Bures-sur-Yvette|Gif-sur-Yvette|Courtab[oeœ]uf|Sèvres|Issy-les-Moulineaux|"
    r"Boulogne-Billancourt|La\s+Défense|Courbevoie|Nanterre|Mantes-la-Jolie|"
    r"Versailles|Guyancourt|Pessac|Bordeaux|Mérignac|Talence)\b",
    re.I,
)


def enabled(env: dict[str, str] | None = None) -> bool:
    """Actif uniquement quand la boîte Gmail IMAP est configurée et non désactivée."""
    values = env if env is not None else os.environ
    flag = str(values.get("MAIL_ALERTS_ENABLED", "1") or "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return bool(str(values.get("GMAIL_ADDRESS") or "").strip() and str(values.get("GMAIL_APP_PASSWORD") or "").strip())


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", "replace"))
        else:
            parts.append(chunk)
    return " ".join("".join(parts).split())


def _bodies(message: email.message.Message) -> tuple[str, str]:
    text = ""
    html = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if ctype == "text/plain":
                text += "\n" + decoded
            else:
                html += "\n" + decoded
    else:
        payload = message.get_payload(decode=True) or b""
        decoded = payload.decode(message.get_content_charset() or "utf-8", "replace")
        if message.get_content_type() == "text/html":
            html = decoded
        else:
            text = decoded
    return text.strip(), html.strip()


def _detect_provider(sender_addr: str, subject: str) -> str:
    addr = sender_addr.lower()
    subj = filters._fold(subject)
    for key, spec in PROVIDERS.items():
        if any(tok in addr for tok in spec["sender_tokens"]):
            return key
    if "jobteaser" in subj:
        return "jobteaser"
    if "free-work" in subj or "freework" in subj:
        return "freework"
    if "meteojob" in subj:
        return "meteojob"
    if "studentjob" in subj:
        return "studentjob"
    if "campus cyber" in subj or "campuscyber" in subj:
        return "campuscyber"
    if "linkedin" in subj:
        return "linkedin"
    if "indeed" in subj:
        return "indeed"
    if "welcome to the jungle" in subj or "welcometothejungle" in subj or "wttj" in subj:
        return "wttj"
    return ""


def _allowed_offer_url(url: str, domains: tuple[str, ...], hints: tuple[str, ...]) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    host = parsed.hostname.lower().rstrip(".")
    if not any(host == dom or host.endswith(f".{dom}") for dom in domains):
        return False
    path_q = f"{parsed.path}?{parsed.query}".lower()
    if any(skip in path_q for skip in _SKIP_URL_TOKENS):
        return False
    if parsed.path in ("", "/"):
        return False
    return any(hint in path_q for hint in hints)


def _extract_links(text: str, html: str, spec: dict[str, Any]) -> list[tuple[str, str]]:
    found: dict[str, str] = {}
    domains = spec["domains"]
    hints = spec["url_hints"]
    if html and "<a" in html.lower():
        try:
            doc = LH.fromstring(html)
            for anchor in doc.xpath("//a[@href]"):
                href = str(anchor.get("href") or "").strip()
                if not _allowed_offer_url(href, domains, hints):
                    continue
                label = " ".join(" ".join(anchor.itertext()).split())
                if href not in found or (len(label) > len(found[href]) and len(label) <= 140):
                    found[href] = label
        except (ValueError, etree.ParserError):
            pass
    for match in re.findall(r"https://[^\s<>\"']+", text or ""):
        clean = match.rstrip(").,;]")
        if _allowed_offer_url(clean, domains, hints) and clean not in found:
            found[clean] = ""
    return list(found.items())


def _infer_campaign(text: str, default: str) -> str:
    folded = filters._fold(text)
    if any(tok in folded for tok in ("stage", "stagiaire", "internship", "intern ")):
        return "stage"
    if any(tok in folded for tok in filters.JOB_MUST):
        return "job"
    return default


def _infer_city_dept(label: str, context: str) -> tuple[str, str]:
    for source in (label, context[:1800]):
        match = _KNOWN_FR_CITIES_RE.search(source or "")
        if match:
            return match.group(1), source_common.extract_department(source)
    dept = source_common.extract_department(f"{label} {context[:1800]}")
    if dept == "91":
        return "Villebon-sur-Yvette", "91"
    if dept == "78":
        return "Mantes-la-Jolie", "78"
    if dept == "33":
        return "Pessac", "33"
    if dept in {"75", "92", "93", "94"} or "ile-de-france" in filters._fold(context):
        return "Paris", dept or "75"
    return "", dept


_IGNORED_COMPANY_TOKENS = frozenset(
    {
        "paris",
        "france",
        "remote",
        "teletravail",
        "hybride",
        "hybrid",
        "ile de france",
        "ile-de-france",
        "essonne",
        "yvelines",
        "h f",
        "hf",
        "h/f",
        "f/h",
        "cdi",
        "cdd",
        "stage",
        "alternance",
        "job etudiant",
        "linkedin",
        "indeed",
        "welcome to the jungle",
        "wttj",
        "jobteaser",
        "free-work",
        "freework",
        "meteojob",
        "studentjob",
        "campus cyber",
        "campuscyber",
        "hellowork",
        "voir l'offre",
        "postuler",
        "nouvelles offres",
        "alerte emploi",
    }
)


def _clean_company_candidate(raw: str) -> str:
    cand = re.sub(r"\s+", " ", str(raw or "")).strip(" \t\r\n\"'.,:;•|·-–—")
    if not cand:
        return ""
    cand = re.sub(r"\s*\([^)]*\)\s*$", "", cand).strip(" ,.-–—")
    cand = re.sub(
        r",\s*(?:Paris|France|Ile-de-France|Île-de-France|91|75|78|92|93|94|33)\b.*$",
        "",
        cand,
        flags=re.IGNORECASE,
    ).strip()
    if len(cand) < 2 or len(cand) > 80:
        return ""
    if re.fullmatch(r"[\d\s()-]+", cand):
        return ""
    folded = filters._fold(cand)
    if folded in _IGNORED_COMPANY_TOKENS:
        return ""
    city_match = _KNOWN_FR_CITIES_RE.fullmatch(cand)
    if city_match:
        return ""
    if source_common.is_ambiguous_location(cand):
        return ""
    if any(tok in folded for tok in ("nouvelles offres", "alerte ", "voir l'offre", "offre d'emploi")):
        return ""
    return cand


def _infer_company_name(
    anchor_label: str,
    subject: str,
    body_snippet: str,
    provider: str,
) -> str:
    """Extrait le nom d'entreprise depuis l'ancre, le sujet ou le corps d'alerte."""
    for source in (anchor_label, subject, body_snippet[:600]):
        if not source:
            continue
        m_chez = re.search(
            r"(?:^|\s)(?:chez|at|@)\s+([A-Z0-9][^\n|·•—–\-()]{1,60})",
            source,
        )
        if m_chez:
            cleaned = _clean_company_candidate(m_chez.group(1))
            if cleaned:
                return cleaned
        m_label = re.search(
            r"(?:entreprise|soci[eé]t[eé]|company)\s*:\s*([^\n|·•—–]{2,60})",
            source,
            re.IGNORECASE,
        )
        if m_label:
            cleaned = _clean_company_candidate(m_label.group(1))
            if cleaned:
                return cleaned

    for source in (anchor_label, subject):
        if not source:
            continue
        parts = re.split(r"\s+(?:-|—|–|\||·|•)\s+", source)
        if len(parts) >= 2:
            for part in parts[1:]:
                cleaned = _clean_company_candidate(part)
                if cleaned:
                    return cleaned

    if body_snippet:
        m_city_pair = re.search(
            r"([A-Z0-9][\w& .'-]{1,50}?)\s*[·|•\-–]\s*(?:" + _KNOWN_FR_CITIES_RE.pattern + r")",
            body_snippet[:600],
        )
        if m_city_pair:
            cleaned = _clean_company_candidate(m_city_pair.group(1))
            if cleaned:
                return cleaned

    return f"Alerte {provider.title()}"


def _extract_public_email(text: str) -> str:
    addr = application_contact.recipient(text)
    if not addr or "@" not in addr:
        return ""
    dom = addr.split("@", 1)[1].strip().lower()
    if any(dom == portal or dom.endswith(f".{portal}") for portal in _PORTAL_EMAIL_DOMAINS):
        return ""
    return addr


def parse_raw_email(
    raw_bytes: bytes,
    *,
    campaign_filter: str = "",
    geocoder=None,
) -> list[dict[str, Any]]:
    """Extrait les offres manuelles d'un mail d'alerte sans rien exécuter."""
    msg = email.message_from_bytes(raw_bytes)
    sender = parseaddr(str(msg.get("From") or ""))[1]
    subject = _decode_header(msg.get("Subject"))
    provider = _detect_provider(sender, subject)
    if not provider:
        return []
    spec = PROVIDERS[provider]
    text, html = _bodies(msg)
    body_text = source_common.strip_html(html, limit=5000) if html else text
    context = f"{subject}\n{body_text or text}".strip()
    links = _extract_links(text, html, spec)
    if not links:
        return []

    offers: list[dict[str, Any]] = []
    coord_cache: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    for url, anchor_label in links[:15]:
        raw_title = anchor_label if len(anchor_label) >= 6 and "voir" not in filters._fold(anchor_label) else subject
        title = re.sub(r"\s+", " ", raw_title).strip()[:160]
        if not title:
            continue
        inferred = _infer_campaign(f"{title} {context[:600]}", spec["default_campaign"])
        if campaign_filter and inferred != campaign_filter:
            continue
        if inferred == "stage":
            if "stage" not in filters._fold(title):
                title = f"Stage - {title}"
            if not source_common.stage_candidate_ok(title, context[:1500], spec["source"]):
                continue
        else:
            blob = filters._fold(f"{title} {context[:800]}")
            if filters.excluded(blob) or filters.too_senior(title):
                continue
            if not any(word in blob for word in filters.JOB_MUST):
                continue

        city, dept = _infer_city_dept(anchor_label, context)
        lat, lon = source_common.resolve_coordinates(city, dept, geocoder=geocoder, cache=coord_cache)
        if not source_common.within_any_zone(lat, lon, inferred):
            continue

        company_name = _infer_company_name(anchor_label, subject, body_text[:600], provider)
        recruiter_email = _extract_public_email(f"{anchor_label}\n{context[:3000]}")
        offer = source_common.build_offer(
            offer_id=source_common.stable_id(provider, url),
            url=url,
            title=title,
            company=company_name,
            city=city,
            latitude=lat,
            longitude=lon,
            description=f"{subject}\n{body_text[:1200]}",
            source=spec["source"],
            contract_type="stage" if inferred == "stage" else "",
            notes=f"Extrait en lecture seule depuis alerte Gmail ({provider})",
        )
        if recruiter_email:
            offer["email"] = recruiter_email
        offers.append(offer)
    return offers


def search(
    env: dict[str, str] | None = None,
    *,
    campaign: str = "",
    days: int = 14,
    limit: int = 40,
    geocoder=None,
) -> list[dict[str, Any]]:
    """Lit les alertes emploi/stage récentes sur Gmail (`INBOX` readonly)."""
    values = env if env is not None else os.environ
    if not enabled(values):
        return []
    user = str(values.get("GMAIL_ADDRESS") or "").strip()
    password = str(values.get("GMAIL_APP_PASSWORD") or "").strip()
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

    if limit <= 0:
        return []
    uids: set[bytes] = set()
    with imaplib.IMAP4_SSL(IMAP_HOST, timeout=30, ssl_context=ssl.create_default_context()) as imap:
        imap.login(user, password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Sélection INBOX impossible")
        for spec in PROVIDERS.values():
            for token in spec["sender_tokens"]:
                ok, data = imap.search(None, "FROM", f'"{token}"', "SINCE", since)
                if ok == "OK" and data and data[0]:
                    uids.update(uid for uid in data[0].split() if uid.isdigit())
        results: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for uid in sorted(uids, key=int)[-limit:]:
            ok, payload = imap.fetch(uid, "(BODY.PEEK[])")
            if ok != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            for offer in parse_raw_email(payload[0][1], campaign_filter=campaign, geocoder=geocoder):
                if offer["url"] not in seen_urls:
                    seen_urls.add(offer["url"])
                    results.append(offer)
        return results

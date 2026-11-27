"""Lecture des mails HelloWork : confirmations et alertes.

HelloWork envoie deux messages utiles :

- « Votre candidature est arrivée chez X » : la candidature est partie.
- « Finalisez votre candidature sur le site de X » : il reste une étape chez
  le recruteur, la candidature n'est pas complète.

Les relire permet de tenir le suivi à jour sans rien inventer. Les liens
d'offres contenus dans les alertes servent de file d'attente : c'est
l'utilisateur qui a demandé ces mails, le bot ne parcourt pas le site.
"""

from __future__ import annotations

import email
import imaplib
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.header import decode_header
from email.policy import default
from zoneinfo import ZoneInfo

import config
from lxml import etree, html as LH

from . import store
from .text import fold

IMAP_HOST = "imap.gmail.com"
HELLOWORK_FROM_DOMAINS = {"hellowork.com", "emails.hellowork.com"}
LOCAL_TIMEZONE = ZoneInfo("Europe/Paris")
# Les liens d'alerte peuvent passer par un sous-domaine de tracking
# (links.hellowork.com, etc.) : on accepte tout hôte qui finit par hellowork.com.
OFFER_LINK = re.compile(r"https?://(?:[a-z0-9.-]+\.)?hellowork\.com/fr-fr/emplois/(\d+)\.html")
COMPANY_AFTER = re.compile(r"(?:arriv[ée]e chez|site de|chez)\s+(.+?)(?:\.|!|\s*$)", re.I)


def read(password: str, days: int = 60, limit: int = 200) -> list[dict]:
    """Renvoie les mails HelloWork non encore enregistrés, du plus ancien au plus récent.

    Les confirmations déjà traitées ne sont pas retéléchargées. Les alertes
    restent relues tant qu'elles peuvent encore contenir des fiches à reprendre.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    messages: list[dict] = []
    with imaplib.IMAP4_SSL(IMAP_HOST, timeout=40, ssl_context=ssl.create_default_context()) as imap:
        imap.login(config.GMAIL_ADDRESS, password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Sélection de la boîte IMAP impossible")
        status, data = imap.search(None, "FROM", '"hellowork"', "SINCE", since)
        if status != "OK":
            raise RuntimeError("Recherche IMAP HelloWork impossible")
        if not data or not data[0]:
            return []
        ids = data[0].split()[-limit:]
        for uid in ids:
            message_id = _header_id(imap, uid)
            if message_id and store.mail_seen(message_id) and store.mail_kind(message_id) != "alert":
                continue
            status, payload = imap.fetch(uid, "(RFC822)")
            if status != "OK" or not payload or not payload[0] or not isinstance(payload[0], tuple):
                raise RuntimeError("Lecture d’un message IMAP impossible")
            parsed = _parse(payload[0][1])
            if parsed and parsed["message_id"]:
                seen_alert = store.mail_seen(parsed["message_id"]) and parsed["kind"] == "alert"
                if not store.mail_seen(parsed["message_id"]) or seen_alert:
                    messages.append(parsed)
    return messages


def _header_id(imap, uid) -> str:
    try:
        status, payload = imap.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        if status != "OK" or not payload or not payload[0]:
            return ""
        raw = payload[0][1].decode("utf-8", "replace")
        match = re.search(r"Message-ID:\s*(<[^>]+>)", raw, re.I)
        return match.group(1).strip() if match else ""
    except Exception:
        return ""


def _authenticated_hellowork(message: email.message.Message) -> bool:
    """Accept the result of the direct Gmail inbound authentication boundary."""
    senders = message.get_all("From", [])
    if len(senders) != 1 or len(senders[0].addresses) != 1 or senders[0].defects:
        return False
    domain = senders[0].addresses[0].domain.lower()
    if domain not in HELLOWORK_FROM_DOMAINS:
        return False
    results = [str(value) for value in message.get_all("Authentication-Results", [])]
    gmail = [value for value in results if re.match(r"^mx\.google\.com\s*;", value, re.I)]
    if not results or len(gmail) != 1 or gmail[0] != results[0]:
        return False
    # Gmail adds its own result at ingress. Reject any ambiguous result and
    # require alignment with the exact domain of the single From mailbox.
    header = re.sub(r"\([^()]*\)", "", gmail[0])
    dmarc = [rule for rule in header.split(";")[1:] if re.match(r"^\s*dmarc=", rule, re.I)]
    if len(dmarc) != 1 or not re.match(r"^\s*dmarc=pass(?:\s|$)", dmarc[0], re.I):
        return False
    dmarc_from = re.search(r"\bheader\.from=([a-z0-9.-]+)(?=\s|$)", dmarc[0], re.I)
    return bool(dmarc_from and dmarc_from[1].lower() == domain)


def _parse(raw: bytes) -> dict | None:
    message = email.message_from_bytes(raw, policy=default)
    subject = _decode(message.get("Subject"))
    message_id = (message.get("Message-ID") or "").strip()
    if not message_id:
        return None
    body, html = _bodies(message)
    kind, company = _classify(subject)
    if not kind:
        return None
    links = sorted(set(OFFER_LINK.findall(f"{body} {html}")))
    return {
        "message_id": message_id,
        "authenticated_source": _authenticated_hellowork(message),
        "subject": subject,
        "date": _date(message.get("Date")),
        "kind": kind,
        "company": company,
        "offers": links,
        "tracking_urls": _tracking_urls(body, html) if kind == "alert" else [],
    }


def _tracking_urls(body: str, html: str) -> list[str]:
    """Find only the offer buttons in HelloWork alert emails."""
    found: list[str] = []
    for content in (body, html):
        if "<a" not in content.lower():
            continue
        try:
            document = LH.fromstring(content)
        except (ValueError, etree.ParserError):
            continue
        for anchor in document.xpath('//a[@href]'):
            label = fold(anchor.text_content()).replace('’', "'")
            url = anchor.get('href', '').strip()
            parsed = urllib.parse.urlparse(url)
            if (label == "voir l'offre" and parsed.scheme == 'https'
                    and parsed.hostname == 'emails.hellowork.com'
                    and parsed.port in (None, 443) and not parsed.username
                    and parsed.path.startswith('/clic/') and url not in found):
                found.append(url)
    return found


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _resolve_tracking_url(url: str) -> str:
    """Resolve one trusted email link without visiting the destination page."""
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'emails.hellowork.com'
            or parsed.port not in (None, 443) or parsed.username
            or not parsed.path.startswith('/clic/')):
        raise ValueError('lien de suivi HelloWork invalide')
    request = urllib.request.Request(url, method='HEAD')
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=20):
            raise ValueError('lien de suivi sans redirection')
    except urllib.error.HTTPError as exc:
        if exc.code not in (301, 302, 303, 307, 308):
            raise ValueError(f'lien de suivi refusé (HTTP {exc.code})') from exc
        target = urllib.parse.urlparse(urllib.parse.urljoin(url, exc.headers.get('Location', '')))
    match = re.fullmatch(r'/fr-fr/emplois/(\d+)\.html', target.path)
    if (target.scheme != 'https' or target.hostname not in ('hellowork.com', 'www.hellowork.com')
            or target.port not in (None, 443) or target.username or not match):
        raise ValueError('redirection vers une destination non reconnue')
    return match.group(1)


def _classify(subject: str) -> tuple[str, str]:
    folded = fold(subject)
    if "candidature est arrivee chez" in folded:
        return "applied", _company(subject)
    if "finalisez votre candidature" in folded:
        return "to_finish", _company(subject)
    if "alerte" in folded or "nouvelles offres" in folded or "offres d'emploi" in folded:
        return "alert", ""
    return "", ""


def _company(subject: str) -> str:
    match = COMPANY_AFTER.search(subject or "")
    if not match:
        return ""
    name = match.group(1).strip(" .!-–—")
    return name[:80]


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
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
            content_type = part.get_content_type()
            if content_type not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
            if content_type == "text/plain":
                text += decoded
            else:
                html += decoded
    else:
        payload = message.get_payload(decode=True) or b""
        text = payload.decode(message.get_content_charset() or "utf-8", "replace")
    return text, html


def _date(value: str | None) -> str:
    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(value or "")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
        return parsed.astimezone(LOCAL_TIMEZONE).isoformat(timespec="seconds")
    except Exception:
        return datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds")


def import_all(password: str, verbose: bool = True) -> list[dict]:
    """Enregistre les confirmations (« arrivée chez X », « finalisez sur X »).

    Les alertes (nouvelles offres) sont laissées à `alert_urls` : elles servent
    de file de découverte, pas de suivi.
    """
    store.init()
    fresh: list[dict] = []
    for message in read(password):
        if message["kind"] == "alert":
            continue
        if store.mail_seen(message["message_id"]):
            continue
        applied = _apply(message)
        store.remember_mail(
            message["message_id"], message["kind"] if applied else "review_required",
            message["company"], message["subject"],
        )
        if not applied:
            continue
        fresh.append(message)
        if verbose:
            print(f"  {message['kind']:<9} {message['company'] or '—'}  {message['date'][:10]}")
    return fresh


def alert_urls(password: str, verbose: bool = True, limit: int = 20, errors: list[str] | None = None) -> list[str]:
    """Alimente et lit la file persistante des fiches d'alerte à traiter."""
    for message in read(password):
        if message["kind"] != "alert":
            continue
        store.remember_mail(message["message_id"], "alert", "", message["subject"])
        tracking = message.get('tracking_urls') or []
        if not message.get("offers") and not tracking:
            store.set_mail_kind(message["message_id"], "alert_empty")
            if errors is not None:
                errors.append('alertes: aucun lien d’offre reconnu dans un mail')
            elif verbose:
                print('Alerte sans lien d’offre reconnu ; classée pour ne plus être relue.')
            continue
        for offer_id in message["offers"]:
            url = f"https://www.hellowork.com/fr-fr/emplois/{offer_id}.html"
            if store.get(offer_id) is not None:
                store.resolve_alert_offer(offer_id)
                continue
            store.queue_alert_offer(message["message_id"], offer_id, url)
        for url in tracking:
            store.queue_alert_link(message['message_id'], url)
        store.set_mail_kind(message["message_id"], "alert_done")
    for row in store.pending_alert_links(limit):
        try:
            offer_id = _resolve_tracking_url(row['url'])
            store.resolve_alert_link(row['message_id'], row['url'], offer_id)
        except Exception as exc:
            message = f'alertes: résolution d’un lien impossible ({type(exc).__name__})'
            store.retry_alert_link(row['message_id'], row['url'], message)
            if errors is not None:
                errors.append(message)
            elif verbose:
                print(message)
    urls = []
    while len(urls) < limit:
        pending = store.pending_alert_urls(limit)
        if not pending:
            break
        cleared = False
        for row in pending:
            if store.get(row['offer_id']) is not None:
                store.resolve_alert_offer(row['offer_id'])
                cleared = True
            elif row['url'] not in urls:
                urls.append(row['url'])
        if not cleared:
            break
    urls = urls[:limit]
    if verbose and urls:
        print(f"{len(urls)} offre(s) trouvée(s) dans les alertes.")
    return urls


def _apply(message: dict) -> bool:
    # A company name alone does not establish which offer was submitted.
    if message.get("authenticated_source") is not True or len(message.get("offers") or []) != 1:
        return False
    offer = store.get(message["offers"][0])
    if not offer:
        return False
    offer_id = offer["id"]
    company = offer["company"]
    title = offer["title"]

    if message["kind"] == "applied":
        store.add_application(
            offer_id,
            company,
            title,
            channel="hellowork",
            evidence=message["subject"],
            applied_at=message["date"],
            external_id=message["message_id"],
            proof_kind="authenticated_receipt",
            proof_reference=message["message_id"],
        )
    elif message["kind"] == "to_finish":
        added = store.add_application(
            offer_id,
            company,
            title,
            channel="hellowork-redirect",
            evidence=message["subject"],
            applied_at=message["date"],
            mark_offer=False,
            external_id=message["message_id"],
        )
        if added and offer_id:
            store.mark_to_finish_from_alert(offer_id)
    else:
        return False
    return True

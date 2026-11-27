#!/usr/bin/env python3
"""Radar en lecture seule des réponses recruteurs et invitations ATS critiques sur Gmail IMAP."""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import logging
import re
import ssl
import tempfile
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path
from typing import Any

import config
import filters
import notifier

LOGGER = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
DEFAULT_STATE_PATH = config.DATA_DIR / "response-radar-state.json"
MAX_SEEN_IDS = 1000

GENERIC_RADAR_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "hotmail.fr",
        "yahoo.com",
        "yahoo.fr",
        "live.fr",
        "orange.fr",
        "free.fr",
        "sfr.fr",
        "laposte.net",
        "icloud.com",
        "proton.me",
        "protonmail.com",
        "hellowork.com",
        "emails.hellowork.com",
        "mail.hellowork.com",
        "makipeople.com",
        "assessfirst.com",
        "testgorilla.com",
        "shl.com",
        "hirevue.com",
        "codingame.com",
        "hackerrank.com",
        "pymetrics.com",
        "greenhouse.io",
        "lever.co",
        "smartrecruiters.com",
        "myworkdayjobs.com",
        "teamtailor-mail.com",
        "teamtailor.com",
        "recruitee.com",
        "ashbyhq.com",
        "icims.eu",
        "icims.com",
        "taleo.net",
        "successfactors.com",
        "indeed.com",
        "jobalerts.indeed.com",
        "linkedin.com",
        "apec.fr",
        "welcometothejungle.com",
        "jobteaser.com",
    }
)

_GENERIC_COMPANY_HINTS = frozenset(
    {
        "recruteur",
        "no reply",
        "noreply",
        "recrutement",
        "jobs",
        "talent",
        "hellowork",
        "makipeople",
        "assessfirst",
        "testgorilla",
        "greenhouse",
        "lever",
        "smartrecruiters",
        "workday",
        "teamtailor",
        "recruitee",
        "ashby",
        "apec",
        "indeed",
        "linkedin",
        "jobteaser",
        "welcometothejungle",
    }
)

_DOMAIN_STOP_PARTS = frozenset(
    {
        "com",
        "fr",
        "eu",
        "net",
        "org",
        "co",
        "io",
        "jobalerts",
        "talent",
        "emails",
        "email",
        "mail",
        "notification",
        "notifications",
        "reply",
        "noreply",
        "no-reply",
        "recrutement",
        "recruit",
        "careers",
        "career",
        "jobs",
        "job",
        "hr",
        "rh",
        "info",
        "contact",
        "teamtailor-mail",
    }
)

ASSESSMENT_DOMAINS = frozenset(
    {
        "makipeople.com",
        "assessfirst.com",
        "testgorilla.com",
        "shl.com",
        "hirevue.com",
        "codingame.com",
        "hackerrank.com",
        "pymetrics.com",
    }
)

NOISE_DOMAINS = frozenset(
    {
        "emails.hellowork.com",
        "notification.gojob.com",
        "samsic-emploi.fr",
        "info.mistertemp.com",
        "indeed.com",
        "jobalerts.indeed.com",
        "mail.hellowork.com",
    }
)

ASSESSMENT_RE = re.compile(
    r"(?:processus de selection|participer a notre processus|n'oubliez pas votre evaluation|"
    r"evaluation en ligne|test technique|test en ligne|vos resultats|completer votre evaluation|"
    r"assessment|online test)",
    re.I,
)

INTERVIEW_RE = re.compile(
    r"(?:\bentretien\b|echange telephonique|appel telephonique|\bdisponibilites\b|\bcreneau\b|"
    r"\bvisio\b|rencontrer|schedule a call|\binterview\b|contact apres candidature|"
    r"contact sur candidature)",
    re.I,
)

REJECTION_RE = re.compile(
    r"(?:ne pouvons|n'avons pas|pas retenu|pas pu retenir|suite favorable|"
    r"autre candidat|autres candidatures|ne correspond pas|unfortunately|"
    r"regret to inform|not selected|not moving forward|decided not to|"
    r"malheureusement|pas en mesure de donner)",
    re.I,
)

ACK_RE = re.compile(
    r"(?:bien recu|accuse de reception|candidature est arrivee|candidature a bien ete|"
    r"enregistrement de votre candidature|merci d'avoir postule|thank you for applying|"
    r"we received your application|en cours d'etude|en cours d'examen|"
    r"finalisez votre candidature)",
    re.I,
)

NOISE_RE = re.compile(
    r"(?:nouvelles offres|alerte emploi|offres d'emploi n'attendent que vous|"
    r"offres correspondant|decouvrez nos offres|selection d'offres)",
    re.I,
)


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


def _body_text(message: email.message.Message) -> str:
    text = ""
    html = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True) or b""
            decoded = payload.decode(part.get_content_charset() or "utf-8", "replace")
            if ctype == "text/plain" and not text:
                text = decoded
            elif ctype == "text/html" and not html:
                html = decoded
    else:
        payload = message.get_payload(decode=True) or b""
        decoded = payload.decode(message.get_content_charset() or "utf-8", "replace")
        if message.get_content_type() == "text/html":
            html = decoded
        else:
            text = decoded
    raw = text if text.strip() else re.sub(r"<[^>]+>", " ", html)
    return " ".join(raw.split())


def _extract_domain(sender: str) -> str:
    _, addr = parseaddr(sender or "")
    target = addr or (sender or "")
    if "@" not in target:
        return ""
    return target.split("@", 1)[1].strip().lower()


def _norm_company(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", filters._fold(value or "")).strip()


def _sender_domain_token(sender: str) -> str:
    dom = _extract_domain(sender)
    if not dom or any(dom == g or dom.endswith(f".{g}") for g in GENERIC_RADAR_DOMAINS):
        return ""
    parts = [p for p in dom.split(".") if p and p not in _DOMAIN_STOP_PARTS]
    if not parts:
        return ""
    return _norm_company(parts[0])


def _matches_company(offer_company: str, company_hint: str, sender_token: str) -> bool:
    offer_norm = _norm_company(offer_company)
    if len(offer_norm) < 2:
        return False
    hints: list[str] = []
    hint_norm = _norm_company(company_hint)
    if len(hint_norm) >= 2 and hint_norm not in _GENERIC_COMPANY_HINTS:
        hints.append(hint_norm)
    if len(sender_token) >= 2 and sender_token not in _GENERIC_COMPANY_HINTS:
        hints.append(sender_token)
    if not hints:
        return False
    offer_compact = offer_norm.replace(" ", "")
    for hint in hints:
        if offer_norm == hint:
            return True
        if len(offer_norm) >= 3 and len(hint) >= 3:
            if re.search(rf"(?<![a-z0-9]){re.escape(offer_norm)}(?![a-z0-9])", hint):
                return True
            if re.search(rf"(?<![a-z0-9]){re.escape(hint)}(?![a-z0-9])", offer_norm):
                return True
        hint_compact = hint.replace(" ", "")
        if (
            len(offer_compact) >= 4
            and len(hint_compact) >= 4
            and (
                offer_compact == hint_compact
                or hint_compact.startswith(offer_compact)
                or offer_compact.startswith(hint_compact)
            )
        ):
            return True
    return False


def _infer_company(sender: str, subject: str) -> str:
    display, addr = parseaddr(sender or "")
    dom = _extract_domain(sender)
    if display and "@" not in display:
        clean = display.strip(" \"'")
        if clean and clean.lower() not in {"no-reply", "noreply", "recrutement", "jobs"}:
            return clean[:80]
    m = re.search(r"(?:chez|de|pour)\s+([A-Z][\w& .-]{1,40})", subject or "")
    if m:
        return m.group(1).strip()
    if dom:
        parts = [p for p in dom.split(".") if p not in {"com", "fr", "eu", "net", "org", "co", "io", "jobalerts", "talent", "emails", "notification", "reply", "teamtailor-mail"}]
        if parts:
            return parts[0].capitalize()
    return addr[:40] if addr else "Recruteur"


def classify_message(sender: str, subject: str, body: str) -> dict[str, str]:
    """Classe déterministement un message entrant sans aucune mutation."""
    dom = _extract_domain(sender)
    subj_f = filters._fold(subject or "")
    body_f = filters._fold((body or "")[:2000])
    company_hint = _infer_company(sender, subject)

    has_rejection = bool(REJECTION_RE.search(f"{subj_f} {body_f[:1600]}"))
    has_assessment = (
        dom in ASSESSMENT_DOMAINS
        or any(dom.endswith(f".{d}") for d in ASSESSMENT_DOMAINS)
        or bool(ASSESSMENT_RE.search(subj_f))
        or bool(ASSESSMENT_RE.search(body_f[:1400]))
    )
    if has_assessment and (not has_rejection or ASSESSMENT_RE.search(subj_f) or dom in ASSESSMENT_DOMAINS):
        return {
            "category": "action_required",
            "reason": "test / évaluation ou processus de sélection en attente",
            "company_hint": company_hint,
        }

    is_noise_sender = (
        dom in NOISE_DOMAINS
        or any(dom.endswith(f".{d}") for d in NOISE_DOMAINS)
        or "alertes@" in (sender or "").lower()
        or "newsletter@" in (sender or "").lower()
    )
    if is_noise_sender and not INTERVIEW_RE.search(subj_f):
        return {
            "category": "noise",
            "reason": "alerte ou newsletter emploi",
            "company_hint": company_hint,
        }
    if NOISE_RE.search(subj_f) and not INTERVIEW_RE.search(subj_f):
        return {
            "category": "noise",
            "reason": "alerte d'offres",
            "company_hint": company_hint,
        }

    if has_rejection:
        return {
            "category": "rejection",
            "reason": "refus détecté",
            "company_hint": company_hint,
        }

    if INTERVIEW_RE.search(f"{subj_f} {body_f[:1400]}"):
        return {
            "category": "action_required",
            "reason": "invitation entretien ou prise de contact recruteur",
            "company_hint": company_hint,
        }

    if ACK_RE.search(f"{subj_f} {body_f[:1200]}"):
        return {
            "category": "ack",
            "reason": "accusé de réception",
            "company_hint": company_hint,
        }

    return {
        "category": "other",
        "reason": "message non classé",
        "company_hint": company_hint,
    }


def _load_state(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("seen_ids") if isinstance(data, dict) else []
        return [str(x) for x in (raw or []) if x]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def _save_state(path: Path, seen_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    trimmed = seen_ids[-MAX_SEEN_IDS:]
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seen_ids": trimmed,
    }
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            tmp_name = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2)
        Path(tmp_name).chmod(0o600)
        Path(tmp_name).replace(path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink(missing_ok=True)


def _find_unique_radar_match(
    store_mod, company_hint: str, subject: str, sender: str
) -> dict[str, Any] | None:
    """Retourne l'offre suivie unique correspondant au signal radar, ou None si ambigu/absent."""
    sender_token = _sender_domain_token(sender)
    candidates: list[dict[str, Any]] = []
    seen_oids: set[str] = set()
    for st in ("applied", "submission_pending", "to_finish", "replied"):
        for row in store_mod.list_offers(status=st, min_score=0, limit=500):
            row_dict = dict(row)
            oid = str(row_dict.get("id") or "")
            if not oid or oid in seen_oids:
                continue
            seen_oids.add(oid)
            candidates.append(row_dict)

    matched = [
        r
        for r in candidates
        if _matches_company(str(r.get("company") or ""), company_hint, sender_token)
    ]
    distinct_companies = {_norm_company(str(r.get("company") or "")) for r in matched}
    if len(distinct_companies) != 1:
        return None
    if len(matched) > 1:
        subj_norm = _norm_company(subject)
        title_hits = [
            r
            for r in matched
            if len(_norm_company(str(r.get("title") or ""))) >= 4
            and _norm_company(str(r.get("title") or "")) in subj_norm
        ]
        if len(title_hits) != 1:
            return None
        matched = title_hits
    return matched[0]


def reconcile_radar_event_to_store(
    category: str,
    company_hint: str,
    subject: str,
    sender: str,
    *,
    store_mod=None,
    prep_mod=None,
) -> dict[str, Any]:
    """Réconcilie de façon déterministe un événement radar avec une offre suivie unique."""
    if category not in ("action_required", "rejection", "ack"):
        return {"matched": False}

    if store_mod is None:
        from hellowork import store as hw_store

        if not hw_store.DB_PATH.exists():
            return {"matched": False}
        store_mod = hw_store
    if prep_mod is None:
        import interview_prep

        prep_mod = interview_prep

    row_dict = _find_unique_radar_match(store_mod, company_hint, subject, sender)
    if row_dict is None:
        return {"matched": False}
    oid = str(row_dict["id"])
    company_name = str(row_dict.get("company") or company_hint or "")
    current_status = str(row_dict.get("status") or "")

    if category == "action_required":
        if current_status != "interview":
            store_mod.set_status(
                oid,
                "interview",
                f"Entretien/test détecté par radar Gmail : {subject[:120]}",
            )
        store_mod.event("radar_interview", oid, f"{company_name} — {subject[:160]}")
        prep_created = False
        url = str(row_dict.get("url") or "").strip()
        if url and prep_mod.load_prep(url) is None:
            contract_low = str(row_dict.get("contract") or "").lower()
            campaign = (
                "alternance"
                if "alternance" in contract_low
                else ("job" if "job" in contract_low else "stage")
            )
            target = {
                "id": oid,
                "url": url,
                "name": company_name,
                "company": company_name,
                "title": str(row_dict.get("title") or ""),
                "city": str(row_dict.get("city") or ""),
                "description": str(row_dict.get("description") or ""),
                "notes": str(row_dict.get("notes") or ""),
                "campaign": campaign,
            }
            prep_data = prep_mod.generate_deterministic_prep(target)
            prep_mod.save_prep(url, prep_data)
            prep_created = True
        return {
            "matched": True,
            "offer_id": oid,
            "company": company_name,
            "status": "interview",
            "prep_created": prep_created,
        }

    if category == "rejection":
        if current_status == "interview":
            return {
                "matched": True,
                "offer_id": oid,
                "company": company_name,
                "status": "interview",
                "prep_created": False,
            }
        store_mod.set_status(oid, "replied", "Refus détecté par radar Gmail")
        store_mod.event("radar_rejection", oid, f"{company_name} — {subject[:160]}")
        return {
            "matched": True,
            "offer_id": oid,
            "company": company_name,
            "status": "replied",
            "prep_created": False,
        }

    store_mod.event("radar_ack", oid, f"{company_name} — {subject[:160]}")
    return {
        "matched": True,
        "offer_id": oid,
        "company": company_name,
        "status": current_status,
        "prep_created": False,
    }


def scan_and_notify(
    password: str,
    *,
    days: int = 14,
    limit: int = 120,
    notify: bool = True,
    sync_store: bool = True,
    state_path: Path | None = None,
    user: str | None = None,
) -> dict[str, Any]:
    """Scanne la boîte INBOX en lecture seule et notifie les réponses/tests critiques inédits."""
    resolved_user = (user or config.GMAIL_ADDRESS or "").strip()
    if not resolved_user or not (password or "").strip():
        return {
            "scanned": 0,
            "action_required": 0,
            "rejections": 0,
            "acks": 0,
            "noise": 0,
            "notified": 0,
            "reconciled": 0,
            "interview_preps_created": 0,
            "items": [],
        }

    path = state_path or DEFAULT_STATE_PATH
    seen_list = _load_state(path)
    seen_set = set(seen_list)

    since = (datetime.now() - timedelta(days=max(1, days))).strftime("%d-%b-%Y")
    summary: dict[str, Any] = {
        "scanned": 0,
        "action_required": 0,
        "rejections": 0,
        "acks": 0,
        "noise": 0,
        "notified": 0,
        "reconciled": 0,
        "interview_preps_created": 0,
        "items": [],
    }

    with imaplib.IMAP4_SSL(
        IMAP_HOST, timeout=30, ssl_context=ssl.create_default_context()
    ) as imap:
        imap.login(resolved_user, password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Sélection INBOX impossible")
        ok, data = imap.search(None, "SINCE", since)
        if ok != "OK" or not data or not data[0]:
            return summary
        uids = [u for u in data[0].split() if u.isdigit()][-max(1, limit) :]
        for uid in uids:
            ok_fetch, payload = imap.fetch(uid, "(BODY.PEEK[])")
            if ok_fetch != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            msg = email.message_from_bytes(payload[0][1])
            msg_id = (msg.get("Message-ID") or "").strip() or f"uid:{uid.decode('ascii', 'ignore')}"
            if msg_id in seen_set:
                continue
            seen_set.add(msg_id)
            seen_list.append(msg_id)
            summary["scanned"] += 1

            sender = _decode_header(msg.get("From"))
            subject = _decode_header(msg.get("Subject"))
            body = _body_text(msg)
            res = classify_message(sender, subject, body)
            cat = res["category"]
            if cat in ("action_required", "rejection", "ack") and sync_store:
                try:
                    rec = reconcile_radar_event_to_store(
                        cat,
                        res["company_hint"],
                        subject,
                        sender,
                    )
                    if rec.get("matched"):
                        summary["reconciled"] += 1
                    if rec.get("prep_created"):
                        summary["interview_preps_created"] += 1
                except Exception as exc:
                    LOGGER.warning(
                        "Réconciliation store radar impossible (%s)",
                        type(exc).__name__,
                    )
            if cat == "action_required":
                summary["action_required"] += 1
                summary["items"].append(
                    {
                        "message_id": msg_id,
                        "company": res["company_hint"],
                        "subject": subject,
                        "reason": res["reason"],
                    }
                )
                if notify:
                    try:
                        if notifier.notify_recruiter_reply(
                            res["company_hint"], subject, body[:300]
                        ):
                            summary["notified"] += 1
                    except Exception as exc:
                        LOGGER.warning(
                            "Notification Telegram réponse impossible (%s)",
                            type(exc).__name__,
                        )
            elif cat == "rejection":
                summary["rejections"] += 1
            elif cat == "ack":
                summary["acks"] += 1
            elif cat == "noise":
                summary["noise"] += 1

    if summary["scanned"] > 0:
        _save_state(path, seen_list)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Radar des réponses/tests ATS Gmail (lecture seule).")
    parser.add_argument("--days", type=int, default=14, help="Fenêtre en jours (défaut: 14).")
    parser.add_argument("--limit", type=int, default=120, help="Nombre max de mails inspectés.")
    parser.add_argument("--notify", action="store_true", help="Envoie les alertes Telegram pour les actions requises inédites.")
    parser.add_argument("--dry-run", action="store_true", help="N'envoie aucune notification.")
    args = parser.parse_args()

    env = config.load_env()
    password = env.get("GMAIL_APP_PASSWORD", "")
    user = env.get("GMAIL_ADDRESS", "")
    result = scan_and_notify(
        password,
        days=args.days,
        limit=args.limit,
        notify=bool(args.notify and not args.dry_run),
        user=user,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

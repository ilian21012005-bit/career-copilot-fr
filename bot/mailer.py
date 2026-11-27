"""Envoi et lecture des réponses via Gmail."""

from __future__ import annotations

import imaplib
import smtplib
import ssl
import time
from datetime import datetime
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Callable

from config import GMAIL_ADDRESS, SENDER_NAME

from runtime_hooks import recovery_paused


def send(
    password: str,
    to: str,
    subject: str,
    body: str,
    attachment: Path | None,
    *,
    max_attempts: int = 2,
    backoff_s: float = 1.0,
    sleep: Callable[[float], None] | None = None,
    attachment_bytes: bytes | None = None,
) -> None:
    message = EmailMessage()
    message["From"] = f"{SENDER_NAME} <{GMAIL_ADDRESS}>"
    message["To"] = to
    message["Reply-To"] = GMAIL_ADDRESS
    message["Subject"] = subject
    message.set_content(body)
    if attachment is not None:
        subtype = "pdf" if attachment.suffix.lower() == ".pdf" else "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        maintype = "application"
        message.add_attachment(
            attachment.read_bytes() if attachment_bytes is None else attachment_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.name,
        )
    sleep_fn = sleep or time.sleep
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        if recovery_paused():
            raise smtplib.SMTPException("Envois suspendus après restauration")
        sending_started = False
        accepted = False
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=40) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(GMAIL_ADDRESS, password)
                if recovery_paused():
                    raise smtplib.SMTPException("Envois suspendus après restauration")
                sending_started = True
                smtp.send_message(message)
                accepted = True
            return
        except smtplib.SMTPAuthenticationError:
            raise
        except smtplib.SMTPServerDisconnected:
            if accepted:
                return
            if sending_started or attempt >= attempts:
                raise
        except smtplib.SMTPException:
            if accepted:
                return
            raise
        except (TimeoutError, OSError):
            if accepted:
                return
            if sending_started or attempt >= attempts:
                raise
        if backoff_s > 0:
            sleep_fn(backoff_s * attempt)


def has_reply(password: str, address: str, since: str = "") -> bool:
    if not address or "@" not in address:
        return False
    sent_at = datetime.fromisoformat(since) if since else None
    if sent_at and sent_at.tzinfo is None:
        sent_at = sent_at.astimezone()
    with imaplib.IMAP4_SSL("imap.gmail.com", timeout=40, ssl_context=ssl.create_default_context()) as imap:
        imap.login(GMAIL_ADDRESS, password)
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Impossible de sélectionner la boîte de réception")
        criteria = ["FROM", f'"{address}"']
        if sent_at:
            months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
            criteria.extend(["SINCE", f"{sent_at.day:02d}-{months[sent_at.month - 1]}-{sent_at.year}"])
        status, data = imap.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("Recherche des réponses Gmail impossible")
        if not data or not data[0]:
            return False
        for uid in data[0].split():
            status, payload = imap.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM DATE)])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                raise RuntimeError("Lecture d'une réponse Gmail impossible")
            message = message_from_bytes(payload[0][1])
            if address.casefold() not in {item.casefold() for _, item in getaddresses(message.get_all('From', []))}:
                continue
            if sent_at:
                try:
                    received_at = parsedate_to_datetime(message.get('Date', ''))
                    if received_at.tzinfo is None:
                        received_at = received_at.astimezone()
                except (TypeError, ValueError, OverflowError) as exc:
                    raise RuntimeError("Date d'une réponse Gmail illisible") from exc
                if received_at < sent_at:
                    continue
            return True
        return False

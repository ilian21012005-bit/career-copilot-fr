"""Module autonome de notifications Telegram pour Career Copilot (compatible monorepo et standalone).

Zéro dépendance externe (utilise uniquement urllib standard).
Détecte automatiquement TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID depuis :
1. Les variables d'environnement
2. Le fichier .env local (`bot/.env`) ou racine du dépôt si présent.
"""

from __future__ import annotations

import html
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT_DIR = HERE.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
LOGGER = logging.getLogger(__name__)
ENV_FILES = [
    HERE / ".env",
    ROOT_DIR / ".env",
    ROOT_DIR / "Job-Etudiant" / "bot" / ".env",
]


def _read_env_files() -> dict[str, str]:
    config: dict[str, str] = {}
    seen: set[Path] = set()
    for path in ENV_FILES:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in config:
                    config[k] = v
        except (OSError, UnicodeError) as exc:
            LOGGER.warning(
                "Impossible de lire la configuration Telegram %s: %s", path, exc
            )
    return config


def get_credentials() -> tuple[str, str]:
    env_vars = _read_env_files()
    token = (
        os.getenv("TELEGRAM_BOT_TOKEN")
        or env_vars.get("TELEGRAM_BOT_TOKEN", "").strip()
    )
    chat_id = (
        os.getenv("TELEGRAM_CHAT_ID") or env_vars.get("TELEGRAM_CHAT_ID", "").strip()
    )
    return token, chat_id


def is_configured() -> bool:
    token, chat_id = get_credentials()
    return bool(token and chat_id)


def send_telegram(
    message: str,
    parse_mode: str = "HTML",
    disable_notification: bool = False,
    timeout: int = 15,
) -> bool:
    """Envoie un message via l'API Telegram."""
    token, chat_id = get_credentials()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": parse_mode,
        "disable_notification": disable_notification,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as exc:
        LOGGER.warning("Échec de l'envoi Telegram (%s)", type(exc).__name__)
        return False


def notify_recruiter_reply(company: str, subject: str, snippet: str = "") -> bool:
    """Notification immédiate lorsqu'un recruteur répond à une candidature."""
    msg = (
        f"🎉 <b>Réponse recruteur reçue !</b>\n\n"
        f"🏢 <b>Entreprise :</b> {html.escape(company or 'Inconnue')}\n"
        f"📩 <b>Objet :</b> {html.escape(subject or 'Sans objet')}\n"
    )
    if snippet:
        clean_snippet = html.escape(snippet.strip()[:600])
        msg += f"\n💬 <b>Extrait :</b>\n<i>« {clean_snippet} »</i>\n"
    return send_telegram(msg)


def notify_merchant_reply(
    nom: str,
    ville: str,
    email_contact: str,
    telephone: str,
    extrait: str,
    reponse_suggeree: str = "",
) -> bool:
    """Notification immédiate lorsqu'un commerçant répond favorablement."""
    msg = (
        f"🔔 <b>Prospect commerçant intéressé !</b>\n\n"
        f"🏪 <b>Commerce :</b> {html.escape(nom or 'Commerce')}\n"
        f"📍 <b>Ville :</b> {html.escape(ville or '—')}\n"
        f"📞 <b>Tél :</b> {html.escape(telephone or '—')} | ✉️ <b>Email :</b> {html.escape(email_contact or '—')}\n\n"
        f"💬 <b>Message du commerçant :</b>\n"
        f"<i>« {html.escape(extrait.strip()[:600])} »</i>\n"
    )
    if reponse_suggeree:
        msg += (
            f"\n💡 <b>Proposition de réponse IA prête :</b>\n"
            f"<code>{html.escape(reponse_suggeree.strip()[:1000])}</code>\n"
        )
    return send_telegram(msg)


def notify_daily_summary(title: str, stats: dict[str, str | int]) -> bool:
    """Envoi du bilan quotidien matinal pour chaque bot."""
    lines = [f"📊 <b>{html.escape(title)}</b>\n"]
    for k, v in stats.items():
        lines.append(f"• <b>{html.escape(str(k))} :</b> {html.escape(str(v))}")
    return send_telegram("\n".join(lines))


def notify_automation(
    bot: str,
    action: str,
    status: str,
    *,
    summary: str = "",
    duration_s: float | int | None = None,
    code: int | None = None,
    disable_notification: bool = False,
    notify: bool | None = None,
) -> bool:
    """Journalise une automation ; Telegram seulement pour les vrais problèmes."""
    try:
        _ops_daemons = ROOT_DIR / "ops" / "daemons"
        if _ops_daemons.is_dir() and str(_ops_daemons) not in sys.path:
            sys.path.append(str(_ops_daemons))
        from automation_events import append_event, format_telegram_message

        record = append_event(
            bot,
            action,
            status,
            summary=summary,
            duration_s=duration_s,
            code=code,
        )
        message = format_telegram_message(record)
    except Exception:
        icon = {"started": "▶", "finished": "✅", "failed": "🔴"}.get(status, "ℹ️")
        message = (
            f"{icon} <b>{html.escape(str(bot))}</b> · {html.escape(str(action))}\n"
            f"{html.escape(str(summary or status))}"
        )
    should_notify = bool(notify) if notify is not None else status == "failed"
    if not should_notify:
        return True
    return send_telegram(message, disable_notification=disable_notification)


def notify_system_alert(title: str, message: str, level: str = "INFO") -> bool:
    """Alerte système."""
    icon = "⚠️" if level == "WARNING" else ("🚨" if level == "ERROR" else "ℹ️")
    msg = f"{icon} <b>{html.escape(title)}</b>\n\n{html.escape(message)}"
    return send_telegram(msg)

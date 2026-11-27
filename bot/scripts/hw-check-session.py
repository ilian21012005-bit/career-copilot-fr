"""Vérifie si la session HelloWork du profil dédié est utilisable.

À lancer APRÈS une connexion manuelle via bash scripts/hw-login.sh, et après avoir
fermé cette fenêtre Chrome (un profil ne peut pas être ouvert deux fois).

Ce script ne se connecte pas, ne résout aucun CAPTCHA et ne masque rien : il
ouvre la page « Mes alertes » avec le Chrome de la machine, sandbox actif, et
rapporte ce que le site répond.

    python scripts/hw-check-session.py

Codes de sortie : 0 = session valide, 2 = pas connecté, 3 = navigateur refusé.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT))

from hellowork.submit_handler import launch_persistent  # noqa: E402

PROFILE = BOT / "data" / "hw-session"
REPORT = PROFILE / "session-check.json"
URL = "https://www.hellowork.com/fr-fr/candidat/mes-alertes.html"
BLOCK_MARKERS = ("browser check failed", "friendly captcha", "accès refusé", "access denied")


def main() -> int:
    playwright, context = launch_persistent(PROFILE, headless=True, sandbox=True)
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        text = page.inner_text("body")
        lowered = text.lower()
        current = page.url

        blocked = any(marker in lowered for marker in BLOCK_MARKERS)
        logged = ("connexion" not in current) and (
            "déconnexion" in lowered or "mes alertes" in lowered
        )
        state = "blocked" if blocked else ("logged_in" if logged else "not_logged_in")

        payload = {
            "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "url": current,
            "state": state,
            "sandbox": True,
        }
        REPORT.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            REPORT.chmod(0o600)
        except OSError:
            pass

        print(f"URL      : {current}")
        print(f"État     : {state}")
        if blocked:
            print("Le site refuse le navigateur automatisé : on s'arrête là.")
            print("Repli prévu : les alertes e-mail HelloWork alimentent le bot.")
            return 3
        if state == "logged_in":
            print("Session valide pour les usages autorisés (lecture de tes pages).")
            return 0
        print("Pas de session : lance d'abord bash scripts/hw-login.sh.")
        return 2
    finally:
        context.close()
        playwright.stop()


if __name__ == "__main__":
    raise SystemExit(main())

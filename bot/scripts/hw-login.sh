#!/usr/bin/env bash
# Connexion manuelle HelloWork dans Google Chrome normal (aucune automatisation).
# Ouvre Chrome avec le profil dédié du bot (data/hw-session) pour enregistrer la session.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT="$(cd "$HERE/.." && pwd)"
PROFILE_DIR="$BOT/data/hw-session"

mkdir -p "$PROFILE_DIR"
chmod 700 "$PROFILE_DIR"

CHROME_BIN="$(which google-chrome 2>/dev/null || which chromium 2>/dev/null || echo "")"
if [[ -z "$CHROME_BIN" ]]; then
    echo "Erreur: Chrome/Chromium introuvable." >&2
    exit 2
fi

URL="https://www.hellowork.com/fr-fr/candidat/connexion-inscription.html#connexion"
echo "Ouverture de Chrome avec le profil dédié : $PROFILE_DIR"
echo "Connectez-vous sur HelloWork puis FERMEZ la fenêtre une fois connecté."

"$CHROME_BIN" \
    --user-data-dir="$PROFILE_DIR" \
    --profile-directory=Default \
    --password-store=basic \
    --use-mock-keychain \
    --no-first-run \
    --no-default-browser-check \
    "$URL"

echo "Chrome fermé. Vous pouvez maintenant exécuter 'python scripts/hw-check-session.py' pour vérifier la session."

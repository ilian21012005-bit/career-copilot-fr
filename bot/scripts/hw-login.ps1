# Connexion manuelle HelloWork dans un Chrome normal (aucune automatisation).
#
# Ce script ouvre Google Chrome avec le profil dedie du bot
# (bot\data\hw-session), sur la page de connexion. Aucun drapeau d'automatisation,
# aucun --no-sandbox : c'est le Chrome de la machine, avec son bac a sable.
#
# 1. Connecte-toi dans la fenetre (le CAPTCHA se comporte comme d'habitude).
# 2. Ferme la fenetre quand tu es sur ton espace.
# 3. La session reste dans le profil ; le bot peut la reutiliser.

param(
    [string]$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
)

$bot = Split-Path -Parent $PSScriptRoot
$profileDir = Join-Path $bot "data\hw-session"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

if (-not (Test-Path $Chrome)) {
    Write-Error "Chrome introuvable : $Chrome"
    exit 2
}

$url = "https://www.hellowork.com/fr-fr/candidat/connexion-inscription.html#connexion"
Start-Process -FilePath $Chrome -ArgumentList @(
    "--user-data-dir=$profileDir",
    "--profile-directory=Default",
    "--no-first-run",
    "--no-default-browser-check",
    $url
)

Write-Output "Chrome normal ouvert avec le profil dedie : $profileDir"
Write-Output "Connecte-toi, puis ferme la fenetre."

"""Résumé court d'une offre (missions), sans appel réseau."""

from __future__ import annotations

_ACTION_START = (
    "création", "creer", "créer", "scripting", "automatiser", "automatisation",
    "développer", "participer", "contribuer", "mettre en place", "piloter",
    "intervenir", "gérer", "gerer", "déployer", "deployer", "administrer",
    "analyser", "sécuriser", "securiser", "intégrer", "integrer", "maintenir",
    "monitorer", "superviser", "concevoir", "implémenter", "implementer",
    "réaliser", "realiser", "assurer", "écrire", "ecrire", "interagir",
)

_NOISE = (
    "nous recherchons", "dans le cadre", "stagiaire ", "h/f", "rejoins",
    "votre profil", "compétences", "competences", "formation", "bac+",
    "durée du stage", "gratification", "à propos", "a propos", "qui sommes",
    "descriptif du poste", "ce poste", "offre d'emploi", "postuler",
    "missions principales", "objectifs", "contexte",
)

_CONTEXTISH = (
    "dans le but", "des applications", "ces outils", "notre équipe",
    "l'entreprise", "environnements isolés",
)

_KEYS = (
    "azure", "linux", "windows", "powershell", "kubernetes", "k8s", "k3s",
    "cloud", "script", "sql", "automat", "devops", "infra",
)


def _trim(line: str, limit: int = 118) -> str:
    text = line if len(line) <= limit else line[:limit].rsplit(" ", 1)[0]
    dangling = {
        "et", "ou", "de", "des", "du", "la", "le", "les", "l'", "d'", "à", "a",
        "dans", "sur", "pour", "avec", "en", "un", "une", "au", "aux", "par",
    }
    words = text.split()
    while words and words[-1].lower().strip(".,;:") in dangling:
        words.pop()
    return " ".join(words).rstrip(".,;: ")


def summarize(description: str = "", missions: str = "", limit: int = 4) -> list[str]:
    """Retourne 3–4 puces actionnables, pas le copier-coller de l'annonce."""
    scored: list[tuple[int, str]] = []
    seen: set[str] = set()
    blob = "\n".join([missions or "", description or ""])

    for raw in blob.splitlines():
        line = " ".join(raw.split()).strip(" -–—•*")
        if not (20 <= len(line) <= 180):
            continue
        low = line.lower()
        if any(n in low for n in _NOISE):
            continue
        if "?" in line:
            continue
        action = any(low.startswith(a) for a in _ACTION_START)
        keyed = any(k in low for k in _KEYS)
        if not (action or keyed):
            continue
        short = _trim(line)
        if len(short) < 18:
            continue
        key = short.lower()[:48]
        if key in seen:
            continue
        seen.add(key)
        score = 0
        if action:
            score += 5
        if keyed:
            score += 2
        if any(c in low for c in _CONTEXTISH):
            score -= 3
        if score <= 0:
            continue
        scored.append((score, short[0].upper() + short[1:]))

    scored.sort(key=lambda x: (-x[0], len(x[1])))
    out = [text for _, text in scored[:limit]]

    if len(out) < 2:
        prose = " ".join(blob.split())
        for part in prose.replace(";", ".").split("."):
            part = part.strip()
            low = part.lower()
            if not (35 <= len(part) <= 140):
                continue
            if any(n in low for n in _NOISE):
                continue
            if not any(k in low for k in _KEYS):
                continue
            short = _trim(part)
            key = short.lower()[:48]
            if key in seen:
                continue
            seen.add(key)
            out.append(short[0].upper() + short[1:])
            if len(out) >= limit:
                break
    return out[:limit]

# AGENTS.md — career-copilot-fr

## Mission

Développer et maintenir **career-copilot-fr**, copilote open source, local et zero-PII de recherche de stages, alternances et jobs étudiants en France (`src/career_copilot/` + `uv` + FastAPI/Uvicorn + Pydantic v2 + SQLite WAL).

## Règles non négociables

1. **Zero PII / Zero secret** : ne jamais lire, afficher ni committer `candidate-profile.json`, `.env`, jetons, bases `*.db`, PDF/DOCX ou données d'un candidat réel. Utiliser exclusivement des personas fictifs (`Alex Martin`, `example.org`).
2. **Périmètre autonome** : aucun import vers un dépôt parent, un autre sous-projet ou des services `systemd` externes dans `src/career_copilot/`. Aucune passe de contexte globale.
3. **Sécurité par défaut** :
   - Écoute locale `127.0.0.1:8765` par défaut.
   - Fichiers privés en `0600`, répertoires privés en `0700`, refus systématique des liens symboliques.
   - Authentification à temps constant (`hmac.compare_digest`) avec jeton d'au moins 32 caractères.
   - Aucun envoi d'email ni soumission automatique pendant les tests (`DISABLE_AI=1`, `AUTOPILOT_SEND=0`).
4. **Anti-hallucination** : toute génération (lettre, CV, préparation d'entretien) s'appuie uniquement sur `facts`, `experiences` et `projects` du profil candidat.
5. **Modularité** : conserver des modules cohérents (< 450 lignes), typés, sans `except Exception` silencieux.

## Commandes de vérification

```bash
# Tests du package src/career_copilot/
PYTHONPATH=src python -m unittest discover -s tests -t . -q

# Suite legacy bot/ (compatibilité Phase A)
cd bot
DISABLE_AI=1 AI_LOCAL_ENABLED=0 AI_GEMINI_ENABLED=0 AI_OPENROUTER_ENABLED=0 \
  python -m unittest discover -s tests -t . -q

# Qualité statique
ruff check src tests
```

## Langue

Réponses, messages d'erreur utilisateur et documentation en français concis.

# career-copilot-fr

Copilote open source, local et **zero-PII** pour organiser la recherche de **stages**, **alternances** et **jobs étudiants** en France.

## Points clés

- **Architecture modulaire `src/`** : package Python `career_copilot` prêt à être extrait en dépôt autonome (`uv`, `pyproject.toml`, console scripts `career-copilot` et `career-copilot-api`).
- **Base SQLite WAL versionnée** : connexion privée `0600`/`0700`, refus des liens symboliques, migrations idempotentes pilotées par `PRAGMA user_version` (`career_copilot.db.migrations`).
- **API HTTP FastAPI + OpenAPI** : factory `create_app()`, authentification constante (`Bearer` / `Basic`), `/healthz`, endpoints typés Pydantic v2 (`/api/v1/status`, `/api/v1/offers`, `/api/v1/applications`, `/api/v1/kits`, `/api/v1/interview-prep/{offer_id}`, `/api/v1/setup`) et interface légère Jinja2 + modules ES natifs.
- **Profil candidat v2 zero-PII** : validation stricte, rétrocompatibilité v1, écriture atomique `0600`, aucun fait inventé.
- **Compatibilité legacy** : les shims `bot/candidate_config.py` et `bot/hellowork/store.py` préservent 100 % des tests et scripts existants durant la migration Phase A.

## Démarrage rapide (`uv`)

```bash
cd Job-Etudiant
uv sync

# Appliquer les migrations SQLite WAL
uv run career-copilot --data-dir ./tmp-data migrate

# Créer un profil fictif d'exemple (Alex Martin, mode 0600)
uv run career-copilot --data-dir ./tmp-data init-example

# Vérifier l'état local (WAL + schéma + profil)
uv run career-copilot --data-dir ./tmp-data health

# Lancer l'API locale sur 127.0.0.1:8765
CAREER_COPILOT_DATA_DIR=./tmp-data uv run career-copilot-api
```

## Qualité & tests

```bash
# Suite package standalone (migrations, API, invariants)
PYTHONPATH=src python -m unittest discover -s tests -t . -q

# Suite complète legacy bot/ (hors ligne, IA désactivée)
cd bot
DISABLE_AI=1 AI_LOCAL_ENABLED=0 AI_GEMINI_ENABLED=0 AI_OPENROUTER_ENABLED=0 \
  python -m unittest discover -s tests -t . -q

# Lint & typage (avec uv sync)
uv run ruff check src tests
uv run ty check src
uv run pytest --cov=career_copilot
```

## Confidentialité & sécurité

- Aucune donnée personnelle (`candidate-profile.json`, `.env`, `*.db`, CV/lettres générés) n'est versionnée.
- Écoute exclusivement sur `127.0.0.1:8765` par défaut.
- Fichiers privés écrits atomiquement en `0600` dans des répertoires `0700` sans liens symboliques.
- L'IA est désactivée par défaut (`AI_ENABLED=0`, `DISABLE_AI=1` coupe tout appel externe).

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — découpage des packages, schéma SQLite WAL et contrat API.
- [RUNBOOK.md](RUNBOOK.md) — exploitation locale, migrations, Docker et extraction en dépôt standalone.
- [AGENTS.md](AGENTS.md) — règles d'ingénierie et garde-fous pour les agents.

# Architecture — career-copilot-fr

## Vue d'ensemble

`career-copilot-fr` suit le layout standard Python `src/` avec séparation stricte entre le socle métier typé (`src/career_copilot/`), la couche legacy en cours de migration (`bot/`) et les données privées locales (jamais versionnées).

```text
Job-Etudiant/
├── pyproject.toml                  # Package uv/PEP 621, ruff, ty, pytest
├── src/career_copilot/
│   ├── __init__.py
│   ├── cli.py                      # Entrée CLI `career-copilot`
│   ├── fs_privacy.py               # Écriture atomique 0600, dossiers 0700, anti-symlink
│   ├── db/
│   │   └── migrations.py           # Connexion SQLite WAL + runner PRAGMA user_version
│   ├── profile/
│   │   ├── presets_access.py       # Accès au catalogue presets sans mutation sys.path
│   │   ├── model.py                # CandidateProfileConfig, règles d'exclusions, exemple v2
│   │   ├── validation.py           # Validation stricte v1/v2 et normalisation
│   │   └── storage.py              # Lecture/écriture 0600, fusion partielle, cache RLock
│   ├── store/
│   │   ├── connection.py           # DatabaseHandle explicite (zéro sys.modules[__name__])
│   │   ├── offers.py               # CRUD offres, filtres, statuts, événements
│   │   ├── applications.py         # Candidatures, déduplication, claims, projections
│   │   ├── plan.py                 # File quotidienne (table plan)
│   │   ├── kits.py                 # Empreintes SHA-256 dossiers & fraîcheur documentaire
│   │   └── alerts.py               # Suivi des mails lus et files de relance alertes
│   ├── api/
│   │   ├── schemas.py              # Modèles Pydantic v2 OpenAPI
│   │   ├── auth.py                 # Jeton >= 32 car., vérification constante Bearer/Basic
│   │   ├── service.py              # Service métier pur (zéro couplage externe/systemd)
│   │   └── app.py                  # Factory FastAPI `create_app()` + runner Uvicorn
│   └── web/
│       ├── templates/index.html    # Shell HTML Jinja2 minimal
│       └── static/                 # Modules ES natifs (`api.js`, `app.js`) et CSS sobre
├── tests/                          # Tests unitaires du package `src/career_copilot`
└── bot/                            # Couche legacy + shims de rétrocompatibilité Phase A
```

## Principes structurants

1. **Injection explicite** : chaque composant reçoit son `DatabaseHandle` ou son `data_dir`. Aucun module dans `src/career_copilot/` n'utilise de passe de contexte globale, ni ne dépend de `systemd` ou d'un autre sous-projet.
2. **SQLite WAL + `PRAGMA user_version`** :
   - Pragmas systématiques : `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, `temp_store=MEMORY`, `cache_size=-8000`.
   - Migrations transactionnelles (`BEGIN IMMEDIATE` → DDL/backfill → `PRAGMA user_version = N` → `COMMIT`).
   - Compatibilité ascendante avec les bases v0 existantes (ajout idempotent des colonnes manquantes et normalisation des statuts `hellowork-redirect`).
3. **Contrat API v1 (`/api/v1/*`)** :
   - `GET /healthz` : sonde non authentifiée (`status`, `version`, `uptime_s`, `sqlite_wal`, `schema_version`, `profile_configured`).
   - `GET /api/v1/status` : agrégats offres/dossiers/candidatures/file du jour.
   - `GET /api/v1/offers`, `GET /api/v1/offers/{offer_id}`, `PATCH /api/v1/offers/{offer_id}/status`.
   - `GET /api/v1/applications`, `POST /api/v1/applications`.
   - `GET /api/v1/kits`.
   - `GET /api/v1/interview-prep/{offer_id}` : fiche d'entretien fondée uniquement sur les `facts` vérifiés du profil.
   - `GET /api/v1/setup`, `PUT /api/v1/setup`.
4. **Rétrocompatibilité Phase A** :
   - `bot/candidate_config.py` délègue intégralement à `career_copilot.profile`.
   - `bot/hellowork/store.py` délègue intégralement à `career_copilot.store` tout en conservant `DB_PATH`, `_INIT_DONE`, `_connect` et `_db` pour la suite de tests existante.

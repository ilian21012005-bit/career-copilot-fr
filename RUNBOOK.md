# Runbook — career-copilot-fr

## 1. Installation locale (`uv`)

```bash
cd Job-Etudiant
uv sync
```

Si `fastapi` / `uvicorn` ne sont pas encore présents dans un environnement Python legacy, le socle `db/`, `profile/`, `store/`, `api/schemas.py`, `api/auth.py` et `api/service.py` reste pleinement exécutable et testable. Exécutez `uv sync` pour activer le serveur FastAPI/Uvicorn.

## 2. Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `CAREER_COPILOT_DATA_DIR` | `./bot/data` | Répertoire privé (`0700`) stockant `hellowork.db`, le jeton API et les dossiers |
| `CANDIDATE_PROFILE_PATH` | `<data_dir>/candidate-profile.json` | Chemin du profil candidat v2 (`0600`) |
| `CAREER_COPILOT_TOKEN` | auto-généré en `0600` | Jeton Bearer/Basic (minimum 32 caractères) |
| `CAREER_COPILOT_HOST` | `127.0.0.1` | Interface d'écoute HTTP (ne jamais exposer hors loopback sans reverse-proxy authentifié) |
| `CAREER_COPILOT_PORT` | `8765` | Port d'écoute HTTP |
| `DISABLE_AI` | `1` en test, `0` sinon | Coupe toute requête IA externe |
| `AUTOPILOT_SEND` | `0` | Doit rester à `0` hors activation explicite par l'utilisateur |

## 3. Exploitation quotidienne

```bash
# 1. Appliquer / vérifier les migrations SQLite WAL
uv run career-copilot --data-dir "$CAREER_COPILOT_DATA_DIR" migrate

# 2. Contrôler la santé locale
uv run career-copilot --data-dir "$CAREER_COPILOT_DATA_DIR" health

# 3. Démarrer l'API locale (loopback uniquement)
uv run career-copilot-api

# 4. Vérifier /healthz
curl -fsS http://127.0.0.1:8765/healthz
```

## 4. Docker standalone (durci)

```bash
docker compose -f docker-compose.yml config
docker compose -f docker-compose.yml up -d
```

Invariants Docker à ne jamais relâcher : publication `127.0.0.1:8765:8765`, utilisateur non-root `10001`, `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`.

## 5. Sauvegarde et restauration

Sauvegarder de façon cohérente une base SQLite WAL à chaud :

```bash
sqlite3 "$CAREER_COPILOT_DATA_DIR/hellowork.db" ".backup '$BACKUP_DIR/hellowork.db'"
chmod 600 "$BACKUP_DIR/hellowork.db"
```

Ne jamais copier uniquement `.db` sans `.backup` ni exposer les sauvegardes dans Git.

## 6. Extraction vers le dépôt autonome `career-copilot-fr`

1. Vérifier que la CI et les tests passent sans aucune fuite PII :
   ```bash
   python bot/career_ctl.py export-standalone /tmp/career-copilot-export --force
   ```
2. Depuis la racine du monorepo parent, isoler l'historique si souhaité :
   ```bash
   git subtree split --prefix=Job-Etudiant -b export/career-copilot-fr
   ```
3. Vérifier l'absence totale de fichiers `.env`, `*.db`, `candidate-profile.json`, PDF/DOCX ou secrets avant toute publication.

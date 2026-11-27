# Career Copilot — Mission Control standalone (profil candidat local).
#
# Contexte de build attendu : racine du monorepo, c'est-à-dire un dossier
# contenant `Job-Etudiant/bot` et `Job-Etudiant/requirements-standalone.txt`.
#
#   docker build -f Job-Etudiant/Dockerfile -t career-copilot .
#   docker compose -f Job-Etudiant/docker-compose.yml up -d
#
# Avec un contexte à la racine, BuildKit lit `Job-Etudiant/Dockerfile.dockerignore`
# (le fichier `Job-Etudiant/.dockerignore` s'applique si le contexte est Job-Etudiant/).
#
# Export standalone aplati (bot/ et requirements-standalone.txt à la racine du
# contexte), si le CLI le produit ainsi :
#   docker build \
#     --build-arg APP_SRC=bot \
#     --build-arg REQUIREMENTS_FILE=requirements-standalone.txt \
#     -f Dockerfile -t career-copilot .

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STANDALONE_CAREER_MODE=1 \
    HOST=0.0.0.0 \
    PORT=8765

ARG APP_SRC=Job-Etudiant/bot
ARG REQUIREMENTS_FILE=Job-Etudiant/requirements-standalone.txt

# Dépendances système pour WeasyPrint 70+ (Pango + HarfBuzz subset + polices Liberation).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Utilisateur non-root sans shell de connexion.
RUN groupadd --gid 10001 copilot \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /app --shell /usr/sbin/nologin copilot

WORKDIR /app

# Dépendances minimales du mode standalone (playwright reste optionnel).
COPY ${REQUIREMENTS_FILE} /tmp/requirements-standalone.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-standalone.txt \
    && rm -f /tmp/requirements-standalone.txt

# Code du bot uniquement : les données runtime sont exclues par .dockerignore.
COPY ${APP_SRC} /app/Job-Etudiant/bot

# Dossiers inscriptibles malgré read_only (montés en volumes nommés au runtime).
RUN mkdir -p /app/Job-Etudiant/bot/data /app/data \
    && chown -R 10001:10001 /app/Job-Etudiant/bot/data /app/data \
    && chmod 0700 /app/Job-Etudiant/bot/data /app/data

WORKDIR /app/Job-Etudiant/bot
USER 10001:10001

EXPOSE 8765

# Mission Control exige Basic Auth : 401 prouve que le serveur écoute et que
# l'authentification est active. 200 est accepté (auth désactivée explicitement).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c 'import urllib.request, urllib.error, sys; exec("try:\n    urllib.request.urlopen(\"http://127.0.0.1:8765/api/health\", timeout=4)\nexcept urllib.error.HTTPError as exc:\n    sys.exit(0 if exc.code == 401 else 1)\nexcept Exception:\n    sys.exit(1)")'

CMD ["python", "app.py", "--persistent"]

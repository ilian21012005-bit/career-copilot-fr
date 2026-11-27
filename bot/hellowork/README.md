# Bot de candidature HelloWork

Rechercher, trier, rédiger, préparer et suivre les candidatures HelloWork
directes avec le profil Chrome dédié et déjà connecté.

## Envoi automatique et intervention ATS

Le cycle quotidien prépare les dossiers. Un cycle lancé avec l’autorisation
d’envoi peut aussi soumettre les candidatures directes HelloWork éligibles.
Les ATS externes et les consentements non reconnus restent à finaliser manuellement.

Les offres redirigées vers un ATS externe, les questions obligatoires non
reconnues et les champs invalides sont bloqués. Le bot ne contourne ni CAPTCHA
ni refus du site. `apply <id> --send` autorise l'envoi direct HelloWork ; pour
un ATS externe, ouvre le dossier préparé et termine toi-même la candidature.

## Démarrage

Depuis `bot/` :

```bash
python -m hellowork init                       # crée la base locale
python -m hellowork add https://www.hellowork.com/fr-fr/emplois/84252266.html
python -m hellowork list                       # offres à 80/100 et plus
python -m hellowork prepare --top 5            # génère 5 dossiers
python -m hellowork report --open              # tableau de bord HTML
```

La tâche planifiée utilise `daily --if-due` pour mettre à jour la file et
préparer les dossiers, sans soumission automatique.

## Le quotidien — automatique

Sur Fedora, le daemon systemd planifie le cycle quotidien et consigne son résultat.
`daily --if-due` ne relance pas un cycle déjà réussi le même jour. Le runtime
utilise des verrous POSIX. L’installation native Windows ne fait plus partie du
périmètre pris en charge.

Le cycle fait tout, sans commande à taper :

1. lire les mails HelloWork (confirmations + offres des alertes) ;
2. enregistrer les nouvelles fiches, les géocoder (BAN), appliquer le rayon 30 km ;
3. dédoublonner (identifiant de fiche + mails déjà lus) ;
4. classer selon le profil BUT 3 ;
5. remplir la file du jour (jusqu'à 20 offres, jamais plus) ;
6. générer CV adapté, lettre PDF, réponses et checklist ;
7. mettre à jour SQLite `data/hellowork.db` et les rapports HTML ;
8. notifier les dossiers à finaliser et enregistrer les candidatures après déclaration manuelle ;
9. écrire le journal et l'état de reprise.

Journaux : `data/hellowork/logs/daily-<date>.log` (détail, UTF-8) et
`task-<horodatage>.log` (démarrage/arrêt de la tâche).
État : `data/hellowork/last-run.json`.

Vérifier le daemon et ses derniers cycles :

```bash
systemctl --user is-active bot-job-etudiant.service
journalctl --user -u bot-job-etudiant.service -n 30 --no-pager
```

Lancer le cycle à la main (même code) : `python -m hellowork daily`.

### Alertes à vérifier dans le compte

Le fichier `data/hellowork/alertes.html` est une aide à la création. Des alertes Villebon ont bien été reçues du 26 au 31 octobre 2026. Le cycle du 02/11/2026 n'a trouvé aucune nouvelle offre à traiter. Vérifier dans le compte les alertes des trois villes :

| Alerte | Localité | Métiers | Contrat | Fréquence |
|---|---|---|---|---|
| Stage informatique Villebon | Villebon-sur-Yvette 91940 | Technicien informatique, Ingénieur sécurité informatique, Développeur informatique | Stage | quotidienne |
| Stage informatique Mantes | Mantes-la-Jolie 78200 | idem | Stage | quotidienne |
| Stage informatique Pessac | Pessac 33600 | idem | Stage | quotidienne |

Le formulaire d'alerte de HelloWork **ne propose pas de champ rayon** : le site
applique son propre rayon. Le bot applique de toute façon son filtre strict de
30 km (Haversine) sur chaque offre reçue, donc une offre trop éloignée est
écartée même si l'alerte l'a remontée.

## Le quotidien (commandes)

```bash
python -m hellowork sync     # 1. lit les mails : confirmations + offres des alertes
python -m hellowork plan     # 2. constitue la file du jour (10-20) et prépare les dossiers
python -m hellowork report   # 3. ouvre data/hellowork/plan.html : la checklist cliquable
```

Pour garder un parcours manuel, ouvre chaque offre, relis-la et envoie sur
HelloWork, puis enregistre l'envoi :

```bash
python -m hellowork apply <id>          # inspecte le premier écran, sans téléverser ni envoyer
python -m hellowork daily --if-due      # prépare et notifie, sans envoi
python -m hellowork skip <id>      # offre écartée (doublon, hors cible…)
```

Les sources d'offres, toutes **autorisées** (aucune page de recherche n'est
parcourue) :

1. **Alertes mail** — crée une alerte sur HelloWork (voir plus bas) ; `sync`
   en extrait les fiches, une par une, avec le cache de 7 jours.
2. **Liens collés** — `add <url>` ou `add --file queue.txt` (une URL par ligne).
3. **Capture HAR** — `add --har capture.har` reprend les fiches vues en session.

Les alertes LinkedIn arrivent sur `le [adresse configurée dans le profil privé]`, connecté dans Codex.
Un suivi quotidien à 9 h lit cette boîte, dédoublonne les liens dans
`data/hellowork/linkedin-alerts.json` et signale les offres pertinentes.
Cette collecte est exécutée par Codex, pas par le service Linux : le service
ne possède pas les identifiants Outlook. Les liens LinkedIn restent séparés
des candidatures automatiques jusqu'à vérification des fiches et des critères.

Pour constituer le stock initial, chercher les annonces publiques, vérifier les
fiches et importer leurs URL avec `add --file queue.txt`. Ensuite les alertes
alimentent les nouveautés. Une page de résultats indiquant des dizaines d'offres
ne signifie pas que ces offres sont déjà importées ni qu'elles conviennent au profil.

La file est **cumulative et idempotente** : relancer `plan` le même jour ne
vide ni ne duplique rien ; il complète jusqu'au plafond. `confirm`/`skip`
enregistrent tout dans SQLite (offres, candidatures, événements, erreurs).

## Mettre en place les alertes HelloWork (2 minutes)

1. Sur HelloWork, connecté à ton compte : fais une recherche « stage
   informatique / cybersécurité » sur chacune des trois villes (Villebon,
   Mantes-la-Jolie, Pessac) avec 30 km de rayon.
2. Clique « Créer mon alerte » pour chaque recherche, fréquence quotidienne.
3. Les nouvelles offres arrivent alors sur `le [adresse configurée dans le profil privé]` ; `sync` les
   récupère — c'est le mécanisme officiel, pas une collecte.

## Les trois zones (30 km chacune)

La recherche n'est plus limitée à l'Île-de-France. Trois centres
indépendants, définis dans `profile.py` :

| Ville | Département | Centre (lat, lon) | Rayon |
|---|---|---|---|
| Villebon-sur-Yvette | 91 | 48.6994, 2.2406 | 30 km |
| Mantes-la-Jolie | 78 | 48.9907, 1.7167 | 30 km |
| Pessac | 33 | 44.8060, -0.6310 | 30 km |

- La distance est une **distance à vol d'oiseau** (Haversine), pas une
  distance routière.
- Une offre est gardée si elle est à **30 km ou moins** d'au moins un centre.
- Le centre le plus proche est stocké comme « ville de référence », avec la
  distance (`zone`, `distance_km` dans SQLite).
- La ville est géocodée via la **Base Adresse Nationale**
  (`api-adresse.data.gouv.fr`), puis filtrée par département. Résultat mis en
  cache dans `data/hellowork/geocache.json`.
- Ville inconnue ou ambiguë : l'offre passe en **« à vérifier »**. Aucune
  distance n'est inventée, elle n'est pas planifiée automatiquement.
- Le score de lieu vaut 15/15 dans la zone, 0 et l'offre est écartée hors zone.
- Doublons : une offre n'a qu'une ligne, et une seule zone de référence (la
  plus proche). Replanifier le même jour ne duplique rien.

Filtrer par zone :

```bash
python -m hellowork list --zone Pessac
python -m hellowork list --location unknown        # les offres à vérifier
python -m hellowork plan --zone "Mantes-la-Jolie"
```

## Le score (sur 100)

| Bloc | Points | Ce qui compte |
|---|---|---|
| Contrat | 25 | stage = 25 ; alternance, CDI, CDD, intérim = écarté |
| Lieu | 15 | à 30 km max d'un des trois centres = 15 ; hors zones = écarté ; inconnu = à vérifier |
| Compétences | 40 | poids des compétences du profil retrouvées dans l'annonce |
| Niveau | 10 | Bac+5 / Master 2 / expérience exigée font baisser, et plafonnent — sauf si l'annonce accepte aussi Bac+3 |
| Fraîcheur | 10 | annonce de la semaine = 9-10 |

Un stage « Bac+5 » ne dépasse pas 60/100, un stage « Master » 79/100. Si
l'annonce mentionne aussi Bac+3, BUT 3, une licence de formation ou niveau 6, le plafond ne
s'applique pas : l'offre reste accessible.

Seuil par défaut : 80. Pour élargir : `list --all`, `prepare --min-score 75`.
Les poids et les compétences sont dans `hellowork/profile.py`, à modifier
librement.

Pour l'envoi automatique, le poste ou ses missions doivent aussi mentionner
la cybersécurité, les systèmes ou les réseaux. Les notes et localisations sont
recalculées avant la sélection, puis vérifiées à nouveau avant l'envoi.

## Commandes

| Commande | Effet |
|---|---|
| `init` | crée `data/hellowork.db` |
| `daily [--if-due] [--no-sync] [--max N]` | cycle complet (mails → dossiers → rapports) |
| `add <url…>` | lit la fiche (une requête, cache 7 jours), note, enregistre |
| `add --file f` / `--har h` | ajoute depuis un fichier ou une capture HAR |
| `list [--status s] [--all] [--zone V] [--location in_zone\|unknown]` | liste triée par score, filtrable par zone |
| `show <id>` | détail, score expliqué, zone et distance |
| `prepare [--top N] [--min-score] [--force] [--dry-run]` | génère les dossiers |
| `plan [--target N] [--max N] [--zone V] [--dry-run]` | file du jour et dossiers, éventuellement limitée à une zone |
| `confirm <id>` | enregistre une candidature réellement envoyée |
| `skip <id>` | écarte une offre de la file |
| `refresh` | recalcule les scores des offres déjà enregistrées |
| `mark <id> <statut>` | `new`, `shortlist`, `prepared`, `applied`, `submission_unknown`, `submission_pending`, `to_finish`, `replied`, `interview`, `ignored` |
| `open <id>` | ouvre l'offre dans le navigateur |
| `sync` | lit les mails HelloWork (confirmations + offres des alertes) |
| `report [--open]` | `data/hellowork/rapport.md` et `.html` + `plan.html` |
| `har <fichier>` | inventaire des requêtes et fiches vues |
| `stats` | compteurs |

## Fichiers

```
bot/hellowork/
  offer.py     lecture d'une fiche (HTML rendu serveur, lxml)
  score.py     note et raisons
  profile.py   profil, compétences, seuils — à éditer
  kit.py       lettre, CV, réponses, checklist
  store.py     SQLite : offres, dossiers, candidatures, mails
  alerts.py    lecture IMAP des mails HelloWork
  daily.py     cycle quotidien (mails → file → dossiers → rapports)
  har.py       analyse d'une capture HAR
  report.py    tableau de bord + file cliquable (plan.html)
  submit_handler.py  simulateur local + candidatures directes HelloWork
  cli.py       ligne de commande
bot/tests/     tests hors réseau + fixture HTML + simulateur local
bot/data/hellowork/  pages en cache, dossiers, rapports, logs, état
```

## Sécurité des identifiants

- `bot/.env` reste local, ignoré par Git et accessible uniquement au compte de service (mode 0600).
- Aucun mot de passe n'apparaît dans les journaux : le cycle ne logue que des
  compteurs, des sociétés et des identifiants d'offres.
- La planification systemd utilise un service utilisateur, sans élévation.
- Les candidatures automatiques sont marquées « envoyées » seulement après une
  confirmation visible du tunnel. Les mails HelloWork et la commande `confirm`
  mettent aussi l'historique à jour.

## Tester le remplissage et l'envoi (simulateur local)

`submit_handler.py` contient le module de clic et de validation de fin de
tunnel, exerçable sans aucun site réel :

```bash
cd bot
pip install playwright            # une seule fois, le Chrome de la machine suffit
python tests/sandbox/demo.py --headless
python -m unittest tests.test_submit_handler -v
```

Ce que ça teste, sur le simulateur `tests/sandbox/app.py` :

- `launch_persistent(user_data_dir)` : contexte persistant, session conservée ;
- `execute_auto_submit(page, offer_id, cv_path=…, letter_text=…)` : repère le
  conteneur du tunnel, injecte le CV (`set_input_files`), remplit la lettre et
  les questions (même celles qui n'apparaissent qu'à l'étape suivante), avance
  jusqu'au bouton final, puis soumet **si** `dry_run=False` et vérifie la
  confirmation ;
- `human_like_delay` : pause de cadence entre les actions, sans mouvement de
  souris ni camouflage ;
- les jetons CSRF du simulateur sont à usage unique : si le token n'est pas
  valide, le serveur répond 403 et le test le montre.

**Garde-fou** : le simulateur reste limité à `127.0.0.1` / `localhost`.
Le mode autorisé accepte uniquement les fiches HTTPS HelloWork et ne suit
jamais les redirections vers un ATS tiers.

## Navigateur et connexion HelloWork

Playwright lance Chromium avec `--no-sandbox` **par défaut** : son option
`chromium_sandbox` vaut `false` tant qu'on ne la passe pas. Le contrôle de
navigateur de HelloWork le détecte (« Browser check failed »). Le correctif est
d'une ligne, dans `launch_persistent()` :

```python
chromium_sandbox=True   # → aucun --no-sandbox dans la ligne de commande
```

Vérifié sur cette machine via `chrome://version` : sans l'option,
`--no-sandbox` est présent ; avec, il disparaît. Les tests
`tests/test_browser_config.py` verrouillent ce réglage.

Ce qui n'est **pas** fait, volontairement : aucun masquage de Playwright, aucun
drapeau `--disable-blink-features=AutomationControlled`, aucune résolution de
CAPTCHA (Friendly Captcha est un CAPTCHA : on s'arrête).

### Connexion manuelle (profil dédié)

```bash
cd bot
powershell -ExecutionPolicy Bypass -File scripts/hw-login.ps1
#  → Chrome normal, profil bot\data\hw-session, page de connexion
#  → connecte-toi, puis FERME la fenêtre
python scripts/hw-check-session.py
```

`hw-login.ps1` ouvre le Chrome de la machine **sans** Playwright ni drapeau
d'automatisation : le contrôle navigateur se comporte comme dans ton Chrome
habituel. Le profil est dédié au bot (`data/hw-session`), ton profil personnel
n'est jamais touché.

`hw-check-session.py` rouvre ce profil avec Playwright (sandbox actif) et lit
« Mes alertes » :

| Sortie | Signification | Suite |
|---|---|---|
| `logged_in` (code 0) | session valide | lecture autorisée possible |
| `not_logged_in` (code 2) | pas de session | relancer `hw-login.ps1` |
| `blocked` (code 3) | le site refuse le navigateur automatisé | **on s'arrête** : les alertes e-mail suffisent |

En cas de refus, la découverte continue de fonctionner par les **mails
d'alerte HelloWork** (`sync` / `daily`), sans navigateur du tout.

## Bon à savoir

- **Pas de contournement.** Un 403/429 remonte une erreur claire ; le bot
  n'insiste pas, ne change pas d'IP, ne résout pas de CAPTCHA.
- **Une requête par fiche**, 3 secondes d'écart minimum, cache de 7 jours.
- **Aucune invention** : la lettre reprend les missions réellement écrites dans
  l'annonce et les expériences du CV. Les compétences que vous n'avez pas sont
  listées dans `reponses.md` sous « à ne pas prétendre ».
- **Les mails** : `sync` ne lit que l'expéditeur `hellowork`, jamais le reste de
  la boîte.
- **Tests** : `python -m unittest discover -s tests -t .` (tests locaux ; aucun
  envoi réel n'est déclenché par cette commande).

## Limites opérationnelles

- Le mode automatique traite seulement les formulaires directs HelloWork. Une
  redirection vers le site d'un recruteur ou un ATS externe reste sans action.
- Les questions obligatoires non reconnues et champs invalides bloquent le clic
  final ; aucune réponse n'est inventée.
- `apply` sans `--send` inspecte l'écran courant sans téléversement ni envoi.
  `daily --auto-submit` est le mode d'envoi du daemon Linux lorsqu'il est explicitement activé.
- L'historique ne marque une candidature envoyée qu'après une confirmation
  détectée. Un clic final sans confirmation place l'offre en
  `submission_unknown` et empêche une nouvelle tentative automatique. Vérifie
  l'espace candidat. La réconciliation navigateur enregistre un reçu lorsqu'il est disponible.
- Si l'espace candidat affiche « En cours d'envoi », l'offre passe en
  `submission_pending`. HelloWork l'a enregistrée mais la livraison au recruteur
  n'est pas encore confirmée. Elle ne sera pas renvoyée automatiquement.
- Une interruption juste avant ou pendant une action susceptible d'envoyer la
  candidature laisse aussi l'offre en `submission_unknown`, à vérifier avant
  toute reprise. Une action bloquée avant ce point peut être retentée.

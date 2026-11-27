# Reconnaissance HelloWork — 25 octobre 2026

Ce document consigne ce qui a été **vérifié** sur le site, et ce qui en découle
pour le bot. Rien n'est supposé : chaque point vient d'une requête réelle ou
d'un fichier public.

## 1. Ce que le site autorise (et interdit)

### robots.txt — https://www.hellowork.com/robots.txt

Extraits pertinents pour `User-Agent: *` :

```
Disallow: /*?
Disallow: /fr-fr/emploi/recherche.html
Disallow: /fr-fr/offres/postuler
Disallow: /fr-fr/emplois/candidature.html
Disallow: /fr-fr/emplois/token/
Disallow: /fr-fr/GetApplyFormFrameView
Disallow: /fr-fr/getinitialformframeview
Disallow: /fr-fr/unleash/gethwcomwebapplyfunnel
Disallow: /fr-fr/api/
Disallow: /fr-fr/candidat/
Disallow: /fr-fr/compte/
```

Conséquences directes :

- les pages de **recherche** (et toute URL avec `?`) ne sont pas moissonnables ;
- le **tunnel de candidature** est explicitement exclu ;
- les fiches `/fr-fr/emplois/<numéro>.html` ne sont **pas** dans la liste
  d'exclusion : une lecture ponctuelle, à la demande de l'utilisateur, reste
  dans le cadre.

### CGU — article 8.2 (page d'accueil, commentaire HTML)

> « L'Utilisateur peut uniquement utiliser le Site aux fins d'accéder aux
> Services, ce exclusivement à des fins privées et non commerciales. Il est
> notamment expressément reconnu et accepté par l'Utilisateur que l'utilisation
> de systèmes automatisés ou de logiciels pour extraire des données du Site, en
> particulier le Contenu et la CVthèque (« capture de données d'écran » /
> « screen scraping / web scraping » notamment), à quelques fins que ce soit,
> commerciales ou non, est strictement interdite, à moins que Hellowork n'ait
> conclu une convention de licence écrite autorisant expressément l'Utilisateur
> à extraire une partie des données du Site. »

C'est la raison pour laquelle le mode de découverte reste basé sur les alertes
et les fiches désignées : il ne parcourt pas les pages de recherche. Depuis le
27 octobre 2026, le dépôt contient aussi un parcours Playwright qui peut
soumettre automatiquement les formulaires HelloWork directs, activé par la
tâche `HelloWork Daily`. Cette implémentation technique ne constitue pas une
autorisation de HelloWork. La restriction de l'article 8.2 et les exclusions
du tunnel dans `robots.txt` ci-dessus restent applicables ; le propriétaire
doit disposer de l'autorisation écrite requise avant d'utiliser ce mode.

## 2. Structure des pages (vérifiée)

### Recherche

- `GET /fr-fr/emploi/recherche.html?k=stage+cybersecurite&l=Ile-de-France`
  répond 200, HTML rendu côté serveur (~600 Ko), ~30 liens de fiches par page.
- Une page de recherche contient 30 liens `/fr-fr/emplois/<id>.html`.
- Utilisée **uniquement** en reconnaissance manuelle, pas par le bot.

### Fiche d'offre

- `GET /fr-fr/emplois/<id>.html` → 200, ~240 Ko, rendu serveur.
- Pas de JSON-LD `JobPosting`, pas de `__NEXT_DATA__`, pas de JSON embarqué :
  tout est dans le HTML, avec des attributs `data-cy` (`jobTitle`,
  `profileCollapseButton`, `applyButtonHeader`, `salary-tag-button`…).
- En-tête : `<h1>` avec un `<span data-cy="jobTitle">` puis un lien
  `/fr-fr/entreprises/<slug>-<id>.html` pour l'entreprise, puis une `<ul>` avec
  la ville et le contrat (`Palaiseau - 91`, `Stage`).
- Corps : deux mises en page coexistent :
  1. sections séparées `Les missions du poste`, `Le profil recherché`
     (souvent replié dans un `<details>`), `Les avantages`,
     `Les étapes de recrutement` ;
  2. une seule section `Détail du poste` qui contient missions + profil.
  Le parseur gère les deux (`SECTION_KEYS` dans `offer.py`).
- Les liens d'analyse (`data-atc-l-value`) sont **obfusqués** (substitution de
  lettres, type ROT13) : signal anti-collecte supplémentaire.
- `#postuler` n'est qu'une ancre : le tunnel de candidature est chargé
  dynamiquement dans `#offer-detail-funnel-container`
  (`GetApplyFormFrameView`, `gethwcomwebapplyfunnel` — tous deux interdits par
  `robots.txt`).

## 3. Ce qui a été observé côté mails

La boîte de l'utilisateur contient 17 mails HelloWork, de deux types :

- « Votre candidature est arrivée chez X » : candidature transmise ;
- « Finalisez votre candidature sur le site de X » : redirection vers l'ATS du
  recruteur, la candidature n'est pas complète.

13 mails exploitables ont été importés par `python -m hellowork sync`, ce qui a
recréé l'historique réel sans aucune saisie manuelle.

## 4. Pourquoi pas de HAR rejoué

Une capture HAR est utile pour **comprendre** et pour **récupérer des liens de
fiches**. Elle ne permet pas de rejouer une candidature :

- les requêtes du tunnel portent des jetons de session et des formulaires
  signés côté serveur ;
- le tunnel change de forme selon l'offre (formulaire HelloWork, redirection
  ATS, candidature par mail) ;
- rejouer l'envoi reviendrait à automatiser exactement ce que l'article 8.2
  interdit.

`python -m hellowork har capture.har` liste les fiches vues et les endpoints
appelés (méthode, chemin, codes), sans rien rejouer.

## 5. Limites connues

- Les sélecteurs peuvent changer : `tests/fixtures/hellowork-offer.html` sert de
  garde-fou, et `python -m unittest discover -s tests -t .` doit rester vert.
- Les annonces en « Détail du poste » mélangent parfois la communication
  d'entreprise et les missions : une relecture du dossier reste recommandée.
- Les offres Bac+5 / Master 2 sont plafonnées à 60/100 même si les compétences
  collent : le stage visé est un stage de BUT 3.
- Le parcours direct HelloWork est automatisé par `submit_handler.py` et la
  tâche quotidienne peut envoyer les offres planifiées. Les formulaires peuvent
  changer ; les champs obligatoires inconnus, les redirections et les CAPTCHA
  arrêtent le traitement. Cette automatisation ne remplace pas l'autorisation
  écrite évoquée à la section 1.

## 6. Autorisation et périmètre d'automatisation

1. Le propriétaire du compte indique avoir une autorisation pour l'utilisation
   de Playwright. La pièce et son périmètre ne sont pas stockés dans le dépôt ;
   respecter exactement les conditions accordées.
2. Le mode Playwright est limité aux fiches HTTPS `www.hellowork.com`, ne suit
   pas les ATS externes, ne résout pas les CAPTCHA et s'arrête si le formulaire
   ne progresse pas ou si une réponse obligatoire est inconnue.
3. Les alertes mail restent la source de découverte ; le téléchargement et la
   soumission automatisés doivent rester couverts par l'autorisation applicable.
4. Suivre les réponses : `sync` classe déjà « envoyée » et « à finaliser ».

## 7. Le module de soumission

Le remplissage de bout en bout existe sur le simulateur local et un chemin
HelloWork direct est activé explicitement. Le flux local s'exerce sur
`tests/sandbox/app.py`, un simulateur
qui reproduit ce qui rend un tunnel difficile : étapes dynamiques, jeton CSRF
à usage unique, upload de fichier, confirmation conditionnelle.

```
python tests/sandbox/demo.py --headless        # remplissage + envoi simulés
python -m unittest tests.test_submit_handler   # 5 tests bout en bout
```

Résultat des tests du simulateur : CV injecté, lettre et questions remplies,
token CSRF consommé, confirmation affichée, envoi enregistré dans
`data/sandbox/submissions.json`. Une inspection Playwright réelle a aussi
confirmé le premier écran du tunnel direct (profil, CV et message) et repéré
des offres qui redirigent vers un recruteur. Aucun envoi réel n'a été effectué
pendant cette inspection.

## 8. Géographie : trois zones, 30 km, géocodage officiel

Les fiches HelloWork ne publient ni latitude ni longitude (vérifié : aucune
occurrence de `latitude`, `longitude` ou `data-lat` dans une fiche). Le lieu
n'est qu'un texte (« Massy - 91 »). Pour appliquer un rayon, il faut donc
géocoder.

- Source utilisée : **Base Adresse Nationale**, `api-adresse.data.gouv.fr`,
  service public, requête `type=municipality`. La réponse est filtrée sur le
  nom exact et le département, puis mise en cache sur disque.
- Distance : **Haversine**, à vol d'oiseau. Aucune distance routière n'est
  utilisée.
- Centres : Villebon-sur-Yvette (48.6994, 2.2406), Mantes-la-Jolie
  (48.9907, 1.7167), Pessac (44.8060, -0.6310). Rayon 30 km.
- Ville non géocodable ou ambiguë : statut `unknown`, offre « à vérifier »,
  jamais planifiée automatiquement.
- Vérifié le 25/10/2026 : Massy → 4 km de Villebon, Paris → 19 km,
  Vélizy-Villacoublay → 10 km, Pessac → 4 km de Pessac, Mantes-la-Jolie →
  1,3 km, ville inventée → aucune coordonnée.

Villebon et Mantes sont distants d'environ 50 km : les deux cercles de 30 km se
recouvrent partiellement. Une offre n'est affectée qu'à la zone la plus proche,
et une fiche n'a qu'une ligne en base : pas de doublon entre zones.

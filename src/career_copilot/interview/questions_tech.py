"""Technical interview question banks for IT, software/data, and engineering presets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from career_copilot.interview.context import project_label


def questions_it_infra_cyber(
    projets: Sequence[Mapping[str, str]],
    *,
    is_pentest: bool,
    is_soc: bool,
    is_grc: bool,
) -> list[dict[str, str]]:
    """Return 5 technical questions for IT infrastructure and cybersecurity interviews."""
    if is_pentest:
        lead = {
            "question": "Quelle méthodologie appliquez-vous pour mener un test d'intrusion sans impacter la production ?",
            "answer": (
                "Je respecte scrupuleusement le cadre d'engagement et le périmètre autorisé (Rules of Engagement). "
                "Je procède d'abord par reconnaissance passive et cartographie non intrusive, puis par vérification manuelle "
                "des vulnérabilités pour écarter les faux positifs. Toute faille critique est signalée immédiatement "
                "au responsable sans exploitation destructive, avec recommandations de remédiation priorisées."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Ne jamais se présenter comme un 'hacker' ni évoquer des tests offensifs hors d'un cadre légal et autorisé.",
        }
    elif is_soc:
        lead = {
            "question": "Face à un pic d'alertes dans le SIEM, quelle est votre démarche pour qualifier un incident potentiel ?",
            "answer": (
                "Je commence par vérifier la cohérence des journaux (horodatage, IP source/destination, compte concerné, actif touché). "
                "Je recoupe l'alerte avec les captures réseau (Wireshark), les signatures IDS/IPS et la matrice MITRE ATT&CK "
                "afin de distinguer une activité légitime d'une compromission réelle, puis j'escalade avec un ticket documenté selon la procédure SOC."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Clôturer ou masquer une alerte en faux positif sans avoir vérifié le contexte de l'hôte et de l'utilisateur.",
        }
    elif is_grc:
        lead = {
            "question": "Comment articulez-vous une analyse de risques avec les contraintes opérationnelles des équipes métier ?",
            "answer": (
                "Une analyse de risques (EBIOS RM, ISO 27001, NIS2) doit rester pragmatique : identifier les biens essentiels "
                "et les scénarios de menace réalistes, puis co-construire des contrôles proportionnés avec les métiers "
                "(moindre privilège, MFA, segmentation, plan de sauvegarde testé) afin d'éviter tout contournement."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Proposer des règles théoriques bloquantes qui encouragent le Shadow IT au lieu d'accompagner les usages.",
        }
    else:
        lead = {
            "question": "Comment concevez-vous l'isolation d'un sous-réseau sensible au sein d'une infrastructure ?",
            "answer": (
                "J'applique la défense en profondeur et le moindre privilège : séparation en VLAN dédiés (administration, serveurs, utilisateurs), "
                "blocage inter-VLAN par défaut sur le pare-feu, ouverture explicite flux par flux documentée et journalisation systématique "
                "des flux sensibles et rejetés."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Croire qu'un simple découpage d'adressage IP sans filtrage pare-feu suffit à isoler un environnement critique.",
        }

    return [
        lead,
        {
            "question": "Pouvez-vous expliquer le fonctionnement d'un tunnel VPN IPsec et l'intérêt du protocole IKEv2 ?",
            "answer": (
                "IPsec chiffre et authentifie les paquets au niveau de la couche réseau. IKEv2 offre une négociation plus rapide, "
                "une meilleure résilience aux changements d'interface (MOBIKE) et l'usage de suites modernes (AES-GCM, PFS) "
                "garantissant la confidentialité persistante des échanges inter-sites ou nomades."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Confondre le mode transport (charge utile seule) et le mode tunnel (encapsulation complète du paquet IP).",
        },
        {
            "question": "Comment filtrez-vous une capture réseau volumineuse dans Wireshark pour isoler une anomalie ?",
            "answer": (
                "Je pars d'une hypothèse précise et j'applique des filtres d'affichage ciblés (ex. tentatives SYN sans ACK, "
                "requêtes DNS inhabituelles ou codes d'erreur applicatifs), puis j'analyse la hiérarchie des protocoles "
                "et les conversations TCP/UDP avant d'inspecter le flux concerné."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Parcourir des milliers de trames séquentiellement sans filtre ni cadrage temporel.",
        },
        {
            "question": "Comment utilisez-vous la conteneurisation Docker et la supervision en environnement d'exploitation ?",
            "answer": (
                "J'isole chaque service dans un conteneur reproductible (images épinglées, volumes dédiés, droits non-root) "
                "et j'instrumente les hôtes et services via des métriques et tableaux de bord (ex. Prometheus / Grafana) "
                "associés à des seuils d'alerte actionnables."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Déployer des conteneurs en mode privilégié sans gestion des secrets ni suivi des journaux.",
        },
        {
            "question": "Si un serveur critique ne répond plus après une mise à jour, quelle est votre démarche de dépannage ?",
            "answer": (
                "J'applique une démarche structurée couche par couche : connectivité réseau et règles pare-feu, "
                "état du service (`systemctl status`) et journaux (`journalctl`), puis comparaison de la configuration versionnée "
                "sous Git afin d'effectuer un retour arrière maîtrisé si la régression est confirmée."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Enchaîner des modifications non tracées en production sans isoler la cause racine.",
        },
    ]


def questions_software_data(projets: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Return 5 technical questions for software engineering and data interviews."""
    return [
        {
            "question": "Comment concevez-vous l'architecture d'une API REST robuste, maintenable et sécurisée ?",
            "answer": (
                "Je sépare clairement la couche transport HTTP, la logique métier et l'accès aux données. "
                "Je valide strictement tous les schémas d'entrée, j'utilise des codes HTTP sémantiques, "
                "je gère l'authentification/autorisation au plus près des ressources et je prévois la pagination et l'idempotence."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Coupler directement les routes HTTP aux requêtes SQL brutes ou exposer les traces d'erreur internes au client.",
        },
        {
            "question": "Quelle stratégie de tests automatisés et d'intégration continue (CI/CD) mettez-vous en place ?",
            "answer": (
                "Je m'appuie sur la pyramide de tests : tests unitaires rapides sur les règles métier et cas limites, "
                "tests d'intégration sur l'API et la base de données isolée, et vérification systématique du linter, "
                "du typage et de la suite de tests à chaque pull request dans le pipeline CI."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Viser un chiffre de couverture artificiel avec des assertions faibles qui ne testent pas les cas d'erreur.",
        },
        {
            "question": "Comment diagnostiquez-vous et optimisez-vous une requête SQL lente en production ?",
            "answer": (
                "J'analyse d'abord le plan d'exécution (`EXPLAIN ANALYZE`) pour repérer les parcours séquentiels coûteux "
                "ou les problèmes de requêtes N+1 côté ORM. J'ajoute ensuite les index composites adaptés aux prédicats de filtrage/tri "
                "et je limite les colonnes et volumes chargés en mémoire."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Multiplier les index au hasard sans mesurer leur impact sur les écritures ni lire le plan d'exécution.",
        },
        {
            "question": "Comment garantissez-vous la qualité des données dans un pipeline de traitement ou d'analyse ?",
            "answer": (
                "Je valide le schéma et les invariants métier dès l'ingestion (valeurs nulles, doublons, bornes temporelles), "
                "je rends chaque étape idempotente et rejouable, et je journalise les métriques de volumétrie et de rejet "
                "pour détecter rapidement toute dérive."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Corriger silencieusement des données corrompues sans tracer l'anomalie à la source.",
        },
        {
            "question": "Quelle est votre méthode pour investiguer un bug intermittent signalé en environnement partagé ?",
            "answer": (
                "Je corrèle les logs structurés et le contexte de la requête pour construire un scénario de reproduction minimal, "
                "j'écris d'abord un test automatisé qui échoue en reproduisant le défaut, puis j'applique le correctif minimal "
                "à la cause racine avant revue de code."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Ajouter un contournement défensif (try/catch muet ou délai arbitraire) sans comprendre l'origine du bug.",
        },
    ]


def questions_engineering_industry(projets: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    """Return 5 technical questions for engineering and industry interviews."""
    return [
        {
            "question": "Quelle démarche qualité appliquez-vous face à une non-conformité détectée en essai ou en production ?",
            "answer": (
                "Je sécurise immédiatement le lot ou le système concerné, puis je mène une analyse de cause racine structurée "
                "(5 Pourquoi, diagramme d'Ishikawa, démarche 8D) avec les opérateurs terrain. Je définis des actions correctives "
                "vérifiables et je mets à jour l'AMDEC ou le plan de surveillance selon le référentiel ISO 9001."
            ),
            "key_project": project_label(projets, 0),
            "pitfall": "Traiter uniquement le symptôme immédiat sans vérifier l'efficacité de l'action corrective dans la durée.",
        },
        {
            "question": "Comment intégrez-vous la sécurité et le respect des normes techniques dès la conception ou sur le terrain ?",
            "answer": (
                "J'identifie dès le cahier des charges les normes applicables, les contraintes HSE et les modes de défaillance critiques. "
                "Chaque modification technique passe par une revue d'impact sécurité, le respect des consignes de consignation/EPI "
                "et une traçabilité documentaire complète."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Considérer la conformité réglementaire et la sécurité comme une simple formalité de fin de projet.",
        },
        {
            "question": "Comment construisez-vous un protocole de validation système pour garantir des essais fiables ?",
            "answer": (
                "Je relie chaque exigence fonctionnelle et physique à un critère d'acceptation mesurable (cycle en V), "
                "je vérifie l'étalonnage des moyens de mesure, je définis les cas nominaux et aux limites, "
                "et je consigne les conditions d'essai pour assurer une parfaite répétabilité."
            ),
            "key_project": project_label(projets, 1),
            "pitfall": "Valider un prototype sur un seul essai nominal sans tester les tolérances ni les dégradations.",
        },
        {
            "question": "Comment gérez-vous les interfaces entre sous-ensembles (mécanique, électronique, contrôle-commande) ?",
            "answer": (
                "Je formalise les contraintes d'interface (encombrement, alimentation, signaux, tolérances thermiques/vibratoires) "
                "dans un document partagé et versionné, avec des revues régulières inter-métiers avant figeage des plans ou du code embarqué."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Modifier localement une cote ou un signal sans notifier les autres métiers impactés.",
        },
        {
            "question": "Comment conduisez-vous un chantier d'amélioration continue (Lean / méthodes) avec les équipes opérationnelles ?",
            "answer": (
                "Je commence par l'observation terrain (Gemba) et l'écoute des opérateurs pour mesurer les temps, les rebuts "
                "et l'ergonomie du poste, puis nous testons des améliorations simples (5S, standardisation) suivies par des indicateurs clairs."
            ),
            "key_project": project_label(projets, 2),
            "pitfall": "Imposer un nouveau standard depuis un bureau sans l'avoir co-construit et testé sur le poste réel.",
        },
    ]

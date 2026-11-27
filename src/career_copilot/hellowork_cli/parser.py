"""Argument parser definition for `python -m hellowork`."""

from __future__ import annotations

import argparse

from career_copilot.hellowork_cli.deps import CliDeps


def build_parser(deps: CliDeps) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hellowork",
        description="Copilote de candidatures HelloWork : lecture d'une fiche, score, dossier, suivi.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="crée la base locale")

    add = sub.add_parser("add", help="ajoute une ou plusieurs fiches")
    add.add_argument("targets", nargs="*", help="URL de fiche HelloWork ou fichier HTML")
    add.add_argument("--file", help="fichier texte, une URL par ligne")
    add.add_argument(
        "--force", action="store_true", help="relit la fiche même si elle est en cache"
    )

    listing = sub.add_parser("list", help="liste les offres enregistrées")
    listing.add_argument("--status", choices=deps.store.STATUSES)
    listing.add_argument("--all", action="store_true", help="y compris les scores faibles")
    listing.add_argument("--min-score", type=int, default=deps.profile.MIN_SCORE)
    listing.add_argument("--limit", type=int, default=40)
    listing.add_argument(
        "--zone",
        choices=[zone["name"] for zone in deps.profile.ZONES],
        help="ne garder qu'une ville de référence",
    )
    listing.add_argument(
        "--location",
        choices=("in_zone", "out_zone", "unknown"),
        help="filtrer par état géographique",
    )

    show = sub.add_parser("show", help="détail d'une offre et de son score")
    show.add_argument("offer_id")

    prepare = sub.add_parser("prepare", help="génère les dossiers des meilleures offres")
    prepare.add_argument("--top", type=int, default=5, help="nombre de dossiers (défaut : 5)")
    prepare.add_argument("--min-score", type=int, default=deps.profile.MIN_SCORE)
    prepare.add_argument("--force", action="store_true", help="refait les dossiers existants")
    prepare.add_argument("--dry-run", action="store_true", help="affiche sans générer")

    refresh = sub.add_parser("refresh", help="recalcule les scores des offres déjà enregistrées")
    refresh.add_argument("--min-score", type=int, default=0)

    plan = sub.add_parser(
        "plan", help="constitue la file du jour (10-20 offres) et prépare les dossiers"
    )
    plan.add_argument("--target", type=int, default=deps.profile.DAILY_TARGET)
    plan.add_argument("--max", type=int, default=deps.profile.DAILY_MAX)
    plan.add_argument("--dry-run", action="store_true", help="affiche la file sans préparer")
    plan.add_argument(
        "--zone",
        choices=[zone["name"] for zone in deps.profile.ZONES],
        help="limiter la file à une ville de référence",
    )

    daily_cmd = sub.add_parser(
        "daily", help="cycle complet : mails, offres, file, dossiers, rapports"
    )
    daily_cmd.add_argument("--no-sync", action="store_true", help="ne pas lire les mails")
    daily_cmd.add_argument(
        "--if-due",
        action="store_true",
        help="ne rien faire si le cycle a déjà tourné aujourd'hui",
    )
    daily_cmd.add_argument("--max", type=int, default=deps.profile.DAILY_MAX)
    daily_cmd.add_argument("--auto-submit", action="store_true", help=argparse.SUPPRESS)

    apply_cmd = sub.add_parser("apply", help="inspecte ou envoie une candidature via Playwright")
    apply_cmd.add_argument("offer_id", nargs="?", help="identifiant de l'offre ; omis avec --daily")
    apply_cmd.add_argument("--daily", action="store_true", help="traiter la file du jour")
    apply_cmd.add_argument("--send", action="store_true", help="autorise le clic final d'envoi")
    apply_cmd.add_argument("--headless", action="store_true", help="ne pas afficher Chrome")
    apply_cmd.add_argument(
        "--accept-consent",
        action="store_true",
        help="cocher les consentements visibles requis (à activer seulement s'ils te conviennent)",
    )

    confirm = sub.add_parser("confirm", help="enregistre une candidature réellement envoyée")
    confirm.add_argument("offer_id")
    confirm.add_argument("--note", default="")

    skip = sub.add_parser("skip", help="écarte une offre de la file du jour")
    skip.add_argument("offer_id")
    skip.add_argument("--note", default="")

    mark = sub.add_parser("mark", help="change le statut d'une offre")
    mark.add_argument("offer_id")
    mark.add_argument("status", choices=deps.store.STATUSES)
    mark.add_argument("--note", default="")
    mark.add_argument(
        "--verified-not-sent",
        action="store_true",
        help="Libère un envoi incertain après vérification de l’espace candidat",
    )

    opened = sub.add_parser("open", help="ouvre l'offre dans le navigateur")
    opened.add_argument("offer_id")

    sync = sub.add_parser("sync", help="lit les mails HelloWork et met le suivi à jour")
    sync.add_argument("--days", type=int, default=365)

    rep = sub.add_parser("report", help="écrit le tableau de bord markdown + HTML")
    rep.add_argument("--min-score", type=int, default=0)
    rep.add_argument("--open", action="store_true")

    deep = sub.add_parser("partner-deep", help="analyse page partenaire + re-score")
    deep.add_argument("--force", action="store_true", help="re-analyse même si déjà fait")
    deep.add_argument("--limit", type=int, default=20)

    rq = sub.add_parser("ready-queue", help="file pret a cliquer (LM+CV+lien)")
    rq.add_argument("--limit", type=int, default=40)
    ac = sub.add_parser("ats-check", help="sonde une URL ATS (Workday/Greenhouse/...)")
    ac.add_argument("url")
    lmq = sub.add_parser("lm-queue", help="file des lettres IA a generer")
    lmq.add_argument("--limit", type=int, default=40)
    lmq.add_argument("--min-score", type=int, default=55)
    lmw = sub.add_parser(
        "lm-write", help="enregistre une lettre IA (stdin ou --file) et rebuild kit"
    )
    lmw.add_argument("--id", required=True)
    lmw.add_argument("--file", help="fichier texte corps de lettre")
    lmr = sub.add_parser("lm-run", help="genere localement via agy/ai_client (si dispo)")
    lmr.add_argument("--limit", type=int, default=5)
    lmr.add_argument("--force", action="store_true")
    js = sub.add_parser("jobspy", help="découverte Indeed/LinkedIn/HelloWork via JobSpy")
    js.add_argument("--dry-run", action="store_true")
    js.add_argument("--results", type=int, default=10)

    sub.add_parser("manual-queue", help="offres fit OK à candidater manuellement")
    sub.add_parser("stats", help="compte les offres et les candidatures")
    return parser

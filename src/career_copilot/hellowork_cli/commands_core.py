"""Core HelloWork CLI commands (init, add, list, show, prepare, refresh, mark, plan, sync)."""

from __future__ import annotations

import sqlite3
import webbrowser
from pathlib import Path
from typing import Any

from career_copilot.hellowork_cli.deps import (
    CliDeps,
    find_offer,
    json_dict,
    json_list,
    short,
    stats_line,
    urls_from_file,
)


def _active_stats_line(deps: CliDeps) -> str:
    return deps.stats_line_fn() if deps.stats_line_fn is not None else stats_line(deps)


def cmd_init(deps: CliDeps, args: Any) -> int:
    _ = args
    print(f"Base prête : {deps.store.DB_PATH}")
    return 0


def cmd_add(deps: CliDeps, args: Any) -> int:
    targets: list[str] = list(args.targets)
    if args.file:
        targets += urls_from_file(Path(args.file))
    if not targets:
        print("Rien à ajouter : donne une URL ou --file.")
        return 2

    added = 0
    for target in dict.fromkeys(targets):
        try:
            offer = deps.offers.read(target, force=args.force)
        except deps.offers.FetchError as exc:
            print(f"  ! {exc}")
            continue
        deps.geo.resolve(offer)
        result = deps.scoring.evaluate(offer)
        deps.store.save_offer(offer, result)
        added += 1
        print(
            f"[{result.value:>3}] {offer.title} — {offer.company} · "
            f"{offer.location_label} → {result.verdict}"
        )
        if result.reasons:
            print("      " + " · ".join(result.reasons))
    print(f"{added} fiche(s) enregistrée(s). `python -m hellowork prepare` pour les dossiers.")
    return 0


def cmd_list(deps: CliDeps, args: Any) -> int:
    min_score = 0 if args.all else args.min_score
    rows = deps.store.list_offers(
        status=args.status,
        min_score=min_score,
        limit=args.limit,
        zone=args.zone,
        location=args.location,
    )
    if not rows:
        total = len(deps.store.list_offers(min_score=0, limit=1))
        print(
            "Aucune offre à ce seuil."
            if total
            else "Aucune offre. Ajoute une fiche : python -m hellowork add <url>"
        )
        if total:
            print("`python -m hellowork list --min-score 60` ou `refresh` pour revoir les scores.")
        return 0
    for row in rows:
        mark = "" if row["status"] == "new" else f"  [{row['status']}]"
        where = f"{row['city'] or ''}"
        if row["zone"] and row["distance_km"] is not None:
            where += f" · {row['zone']} {row['distance_km']:.0f} km"
        elif row["location_status"] == "unknown":
            where += " · à vérifier"
        print(
            f"[{row['score']:>3}] {row['id']:<9} {row['company'][:22]:<22} "
            f"{row['title'][:46]:<46} {where}{mark}"
        )
    print(f"\n{len(rows)} offre(s) — détail : python -m hellowork show <id>")
    return 0


def cmd_show(deps: CliDeps, args: Any) -> int:
    row = find_offer(deps, args.offer_id)
    if not row:
        print(f"Offre inconnue : {args.offer_id}")
        return 1
    result = deps.scoring.Score(
        value=row["score"],
        parts=json_dict(row["score_parts"]),
        reasons=json_list(row["reasons"]),
        gaps=json_list(row["gaps"]),
        zone=row["zone"] or "",
        distance_km=row["distance_km"],
        location_status=row["location_status"] or "unknown",
    )
    print(f"{row['title']}")
    dept = f"({row['department']})" if row["department"] else ""
    print(f"{row['company']} — {row['city'] or ''} {dept}")
    if row["zone"] and row["distance_km"] is not None:
        print(f"zone : {row['zone']} · {row['distance_km']:.1f} km à vol d'oiseau")
    elif (row["location_status"] or "") == "unknown":
        print("zone : à vérifier (localisation non géocodable)")
    print(f"{row['url']}")
    print(f"statut : {row['status']}   vu le : {row['first_seen'][:10]}")
    print()
    print(result.explain())
    saved = deps.store.kit_for(row["id"])
    if saved:
        print("\nDossier :")
        print(f"  {saved['letter_path']}")
        print(f"  {saved['cv_path']}")
    print("\nExtrait :")
    print(short(row["description"] or row["missions"] or "", 900))
    return 0


def cmd_prepare(deps: CliDeps, args: Any) -> int:
    wanted = ("new", "shortlist", "prepared") if args.force else ("new", "shortlist")
    rows = [
        row
        for row in deps.store.list_offers(min_score=args.min_score, limit=200)
        if row["status"] in wanted
    ][: args.top]
    if not rows:
        print("Aucune offre au-dessus du seuil. `python -m hellowork add <url>` d'abord.")
        return 0
    made = 0
    for row in rows:
        existing_kit = deps.store.kit_for(row["id"])
        if existing_kit and not args.force:
            if deps.store.kit_is_current(row["id"], existing_kit):
                print(f"  = {row['company']} — dossier déjà prêt")
            else:
                print(
                    f"  ! {row['company']} — dossier périmé ; relire l'offre et régénérer avec --force"
                )
            continue
        if args.dry_run:
            print(f"  · {row['score']} {row['company']} — {row['title']} (dry-run)")
            continue
        offer = deps.offers.from_row(row)
        result = deps.scoring.evaluate(offer)
        deps.store.save_offer(offer, result)
        try:
            files = deps.kit.build(offer, result)
        except ValueError as exc:
            print(f"  ! {row['company']} — {exc}")
            continue
        deps.store.save_kit(
            row["id"],
            files["subject"],
            files["letter"],
            files["cv"],
            files["dossier"],
        )
        deps.store.set_status(row["id"], "prepared")
        made += 1
        print(f"  + {result.value} {row['company']} → {files['folder']}")
    if made:
        print(f"\n{made} dossier(s). Ouvre l'offre, relis, envoie : python -m hellowork open <id>")
    return 0


def cmd_refresh(deps: CliDeps, args: Any) -> int:
    rows = deps.store.list_offers(min_score=args.min_score, limit=1000)
    changed = 0
    for row in rows:
        offer = deps.offers.from_row(row)
        if offer.latitude is None or offer.longitude is None:
            deps.geo.resolve(offer)
        result = deps.scoring.evaluate(offer)
        if result.value != row["score"]:
            changed += 1
            print(
                f"  {row['company'][:24]:<24} {row['score']:>3} → {result.value:>3}  ({result.verdict})"
            )
        deps.store.save_offer(offer, result)
    print(f"{len(rows)} offre(s) revue(s), {changed} score(s) modifié(s).")
    return 0


def cmd_mark(deps: CliDeps, args: Any) -> int:
    row = find_offer(deps, args.offer_id)
    if not row:
        print(f"Offre inconnue : {args.offer_id}")
        return 1
    if args.verified_not_sent:
        updated = deps.store.release_uncertain_submission(row["id"], args.status, args.note)
    elif args.status == "applied":
        updated = deps.store.declare_manual_application(
            row["id"], channel="hellowork-manual", note=args.note
        )
    else:
        allowed = ("new", "shortlist", "prepared", "ignored")
        if args.status in ("interview", "replied"):
            allowed += ("applied", "interview", "replied")
        updated = deps.store.set_status(
            row["id"], args.status, args.note, expected_statuses=allowed
        )
    if not updated:
        print("Transition refusée : l’état actuel de la candidature est conservé.")
        return 1
    print(f"{row['company']} → {args.status}")
    return 0


def cmd_plan(deps: CliDeps, args: Any) -> int:
    chosen = deps.daily.build(args.target, args.max, zone=args.zone)
    print(f"File du jour : {len(chosen)} offre(s) (objectif {args.target}, max {args.max}).")
    for row in chosen:
        state = "prêt" if row["status"] == "prepared" else "à préparer"
        where = row["zone"] or "à vérifier"
        distance = f" {row['distance_km']:.0f} km" if row["distance_km"] is not None else ""
        print(
            f"  {row['score']:>3}  {row['company'][:22]:<22} {row['title'][:40]:<40} "
            f"{where}{distance} [{state}]"
        )
    if args.dry_run:
        print("dry-run : aucun dossier généré.")
        return 0
    made = deps.daily.prepare()
    print(f"{len(made)} dossier(s) préparé(s).")
    result = deps.report.build()
    print(f"File cliquable : {result['plan']}")
    print(f"Reste à envoyer aujourd'hui : {deps.daily.remaining_today()}")
    return 0


def cmd_confirm(deps: CliDeps, args: Any) -> int:
    row = find_offer(deps, args.offer_id)
    if not row:
        print(f"Offre inconnue : {args.offer_id}")
        return 1
    if deps.store.confirm(row["id"], note=args.note):
        print(f"{row['company']} → envoyée (confirmée).")
    else:
        print(f"{row['company']} déjà enregistrée aujourd'hui.")
    deps.report.build()
    return 0


def cmd_skip(deps: CliDeps, args: Any) -> int:
    row = find_offer(deps, args.offer_id)
    if not row:
        print(f"Offre inconnue : {args.offer_id}")
        return 1
    deps.store.skip(row["id"], args.note)
    print(f"{row['company']} → écartée.")
    deps.report.build()
    return 0


def cmd_open(deps: CliDeps, args: Any) -> int:
    row = find_offer(deps, args.offer_id)
    if not row:
        print(f"Offre inconnue : {args.offer_id}")
        return 1
    saved = deps.store.kit_for(row["id"])
    if saved:
        print(f"Dossier : {Path(saved['letter_path']).parent}")
    webbrowser.open(row["url"])
    print(f"Ouvert : {row['url']}")
    return 0


def cmd_sync(deps: CliDeps, args: Any) -> int:
    _ = args
    env = deps.load_env()
    password = env.get("GMAIL_APP_PASSWORD", "")
    if not password:
        print("GMAIL_APP_PASSWORD manque dans bot/.env")
        return 2
    print("Lecture des mails HelloWork…")
    fresh = deps.alerts.import_all(password)
    print(f"{len(fresh)} nouveau(x) mail(s).")

    errors: list[str] = []
    urls = deps.alerts.alert_urls(password, errors=errors)
    fetch_err = getattr(deps.offers, "FetchError", RuntimeError)
    for url in urls:
        try:
            offer = deps.offers.read(url)
            deps.geo.resolve(offer)
            result = deps.scoring.evaluate(offer)
            deps.store.save_offer(offer, result)
            deps.store.resolve_alert_offer(offer.id)
        except (fetch_err, OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
            print(f"  ! {exc}")
            errors.append("offre: traitement impossible")
            deps.store.retry_alert_offer(deps.offers.offer_id(url), str(exc))
            continue
        where = f"{offer.zone} {offer.distance_km:.0f} km" if offer.zone else "à vérifier"
        print(f"[{result.value:>3}] {offer.company} — {offer.title} · {where} → {result.verdict}")

    for error in errors:
        print(f"  ! {error}")
    print(_active_stats_line(deps))
    return 1 if errors else 0


def cmd_report(deps: CliDeps, args: Any) -> int:
    result = deps.report.build(min_score=args.min_score)
    print(_active_stats_line(deps))
    print(f"Markdown : {result['markdown']}")
    print(f"HTML     : {result['html']}")
    if args.open:
        webbrowser.open(result["html"].resolve().as_uri())
    return 0


def cmd_stats(deps: CliDeps, args: Any) -> int:
    _ = args
    print(_active_stats_line(deps))
    for status, count in sorted(deps.store.counts().items()):
        print(f"  {status:<10} {count}")
    print("Zones :")
    for zone, count in deps.store.zone_counts().items():
        print(f"  {zone:<22} {count}")
    return 0

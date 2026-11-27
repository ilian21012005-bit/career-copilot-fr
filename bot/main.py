"""Recherche du matin : entreprises, annonces, mails, récap.

Sans envoi :  python main.py --dry-run
Mail de test : python main.py --send-test
Vrai envoi :  python main.py --send
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import adzuna
import apec
import candidate_config
import csp_offres
import filters
import jooble
import lba
import offres
import pass_offres
import letters
import mail_alerts
import mailer
import offer_letters
import pdfs
import recruitee
import smartrecruiters
import store
import suivi
import teamtailor
import workday
import wttj
from config import (
    ADZUNA_JOB_QUERIES,
    ADZUNA_STAGE_QUERIES,
    DATA_DIR,
    GLOBAL_CAP,
    JOB_CAP,
    JOOBLE_JOB_QUERIES,
    STAGE_CAP,
    STAGE_ROME_FALLBACK,
    ZONES,
    load_env,
)
from private_storage import write_private_text


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Candidatures stage informatique BUT 3 et job étudiant"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Affiche les cibles, n'envoie rien"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Autorise l'envoi des candidatures et relances",
    )
    parser.add_argument(
        "--flush-queue",
        action="store_true",
        help="Envoie uniquement les emails déjà en file (mail_queue)",
    )
    parser.add_argument(
        "--force-run",
        action="store_true",
        help="Relance le cycle même s'il a déjà réussi aujourd'hui",
    )
    parser.add_argument(
        "--skip-public-ats",
        action="store_true",
        help="Ignore les ATS publics dans la collecte (gérés par hellowork daily)",
    )
    parser.add_argument(
        "--send-test", action="store_true", help="Envoie un essai à ta propre adresse"
    )
    parser.add_argument(
        "--pending-mails",
        action="store_true",
        help="Liste les envois incertains à vérifier",
    )
    parser.add_argument(
        "--resolve-mail",
        metavar="ID",
        help="Résout un envoi incertain après vérification Gmail",
    )
    parser.add_argument(
        "--mail-result",
        choices=("sent", "not-sent"),
        help="Résultat de la vérification",
    )
    args = parser.parse_args()

    env = load_env()
    if args.flush_queue:
        store.init()
        if args.dry_run or not args.send:
            print(f"File en attente (dry-run) : {len(store.pending_email())} email(s).")
            return 0
        if not env.get("GMAIL_APP_PASSWORD") or not env.get("GMAIL_ADDRESS"):
            print(
                "GMAIL_ADDRESS ou GMAIL_APP_PASSWORD manquant : flush-queue indisponible."
            )
            return 1
        pdf_paths = pdfs.ensure_pdfs()
        warnings: list[str] = []
        emailed = _flush_mail_queue(env, pdf_paths, warnings)
        print(
            f"Flush mail_queue terminé : {len(emailed)} envoyé(s), {len(store.pending_email())} en attente."
        )
        for warning in warnings:
            print(warning, file=sys.stderr)
        return 1 if warnings else 0
    recipient = str(env.get("GMAIL_ADDRESS") or "").strip()
    if not args.dry_run and (
        args.pending_mails or args.resolve_mail or args.mail_result
    ):
        store.init()
        if args.resolve_mail and args.mail_result:
            previous = store.get_target(args.resolve_mail)
            resolved = store.resolve_uncertain(
                args.resolve_mail, args.mail_result == "sent", release_email_claim=True
            )
            warnings = []
            _reconcile_mail_projections(warnings)
            for warning in warnings:
                print(warning, file=sys.stderr)
            if resolved or (previous and previous["projection_pending"]):
                print("État de l'envoi mis à jour.")
                return int(bool(warnings))
            print("Aucun envoi incertain avec cet identifiant.")
            return 1
        if args.resolve_mail or args.mail_result:
            print("Utilise --resolve-mail ID avec --mail-result sent ou not-sent.")
            return 2
        pending = store.uncertain_targets()
        for row in pending:
            print(f"{row['id']} — {row['name']} — {row['status']}")
        print(f"{len(pending)} envoi(s) à vérifier dans les messages envoyés Gmail.")
        return 0
    if args.send_test and not args.dry_run:
        if not env.get("GMAIL_APP_PASSWORD"):
            print("GMAIL_APP_PASSWORD manque dans bot/.env.")
            return 2
        if not recipient:
            print("GMAIL_ADDRESS manque dans la configuration privée.")
            return 2
        pdf_paths = pdfs.ensure_pdfs()
        mailer.send(
            env["GMAIL_APP_PASSWORD"],
            recipient,
            "Test — script candidatures",
            "Le script peut envoyer un CV. Ceci est l'essai, aucune entreprise n'a été contactée.\n",
            pdf_paths["stage"],
        )
        print("Mail de test envoyé à " + (recipient))
        return 0

    store.init()
    if args.dry_run or not args.send:
        warnings: list[str] = []
        pending = store.uncertain_targets()
        if pending:
            warnings.append(
                f"{len(pending)} envoi(s) incertain(s) à vérifier : python main.py --pending-mails"
            )
        days = _catchup_days()
        targets = _gather(env, days, warnings, skip_public_ats=args.skip_public_ats)
        fresh = _fresh(targets)
        _print_dry(fresh, warnings, days)
        print(f"En file pour le prochain envoi : {len(store.pending_email())}")
        return 0
    if not env.get("GMAIL_APP_PASSWORD"):
        print("GMAIL_APP_PASSWORD manque dans bot/.env : envoi annulé.")
        return 2
    pdf_paths = pdfs.ensure_pdfs()
    raw_interval = (
        os.getenv("MAIN_MIN_INTERVAL_SECONDS")
        or env.get("MAIN_MIN_INTERVAL_SECONDS")
        or "10800"
    )
    try:
        min_interval = max(0, int(raw_interval))
    except (TypeError, ValueError):
        min_interval = 10800
    if store.ran_recently(min_interval) and not args.force_run:
        print("Déjà envoyé récemment sur ce créneau. Prochaine recherche plus tard.")
        return 0
    try:
        warnings: list[str] = []
        run_id: int | None = None
        pending = store.uncertain_targets()
        if pending:
            warnings.append(
                f"{len(pending)} envoi(s) incertain(s) à vérifier : python main.py --pending-mails"
            )
        days = _catchup_days()
        targets = _gather(env, days, warnings, skip_public_ats=args.skip_public_ats)
        fresh = _fresh(targets)
        emailed: list[dict] = []
        digest: list[dict] = []
        replies: list[str] = []
        relanced: list[str] = []
        run_id = store.start_run()
        new_rows = suivi.add_many(fresh)
        try:
            import source_common

            stage_direct = [
                t for t in fresh if t.get("campaign") == "stage" and not t.get("alternance")
            ]
            alt_direct = [
                t
                for t in fresh
                if t.get("campaign") == "alternance" or t.get("alternance") is True
            ]
            job_direct = [
                t for t in fresh if t.get("campaign") == "job" and not t.get("alternance")
            ]
            if stage_direct:
                source_common.ingest_stage_offers_to_store(stage_direct)
            if alt_direct:
                source_common.ingest_alternance_offers_to_store(alt_direct)
            if job_direct:
                source_common.ingest_job_offers_to_store(job_direct)
        except Exception as exc:
            warnings.append(
                f"Synchro Mission Control partielle ({type(exc).__name__})."
            )
        # Persist before SMTP so a restart or a daily cap cannot lose an offer.
        for target in fresh:
            if target.get("email"):
                store.queue_email(target)
        emailed = _flush_mail_queue(env, pdf_paths, warnings)

        for target in fresh:
            if not target.get("email"):
                digest.append(target)
                _remember(target, "digest")

        relanced, replies = _relances(env, pdf_paths, warnings)
        summary = _summary(emailed, digest, relanced, replies, warnings)
        summary += f"\nCandidatures par mail en attente du prochain cycle : {len(store.pending_email())}.\n"
        summary += (
            f"\nNouvelles lignes dans le Excel : {new_rows}.\n"
            "Coche Postulé et Statut dans le fichier sur le PC, pas seulement dans le mail :\n"
            f"{suivi.SUIVI_PATH}\n"
        )
        first_success_today = not store.already_ran_today(25 * 3600)
        has_recap_activity = bool(emailed or digest or relanced or replies or warnings)
        if first_success_today or has_recap_activity:
            if recipient:
                mailer.send(
                    env["GMAIL_APP_PASSWORD"],
                    recipient,
                    "Récap candidatures",
                    summary,
                    suivi.SUIVI_PATH if suivi.SUIVI_PATH.exists() else None,
                )
            else:
                warnings.append(
                    "Récapitulatif non envoyé : GMAIL_ADDRESS manque dans la configuration privée."
                )
        store.finish_run(run_id, summary)
        print(summary)
        return 0
    except Exception:
        detail = traceback.format_exc()
        if run_id is not None:
            try:
                store.finish_run(run_id, f"Échec du cycle : {detail[-2000:]}")
            except Exception:
                pass
        _report_crash(env, detail)
        print(detail, file=sys.stderr)
        return 1


def _mail_offer_id(target: dict) -> str:
    explicit_id = str(target.get("hw_offer_id") or "").strip()
    if explicit_id:
        return explicit_id
    match = re.search(r"/emplois/(\d+)\.html", str(target.get("url") or ""))
    return match.group(1) if match else ""


def _reconcile_mail_projections(warnings: list[str]) -> None:
    from hellowork import store as hw_store

    for row in store.unapplied_mail_projections():
        target = dict(row)
        try:
            if target.get("queue_payload"):
                payload = json.loads(target["queue_payload"])
                for key in ("hw_offer_id", "title"):
                    target[key] = target.get(key) or payload.get(key)
            offer_id = _mail_offer_id(target)
            if offer_id:
                hw_store.init()
            target_id = target["id"]
            if target["status"] == "sending_cancelled":
                if offer_id:
                    hw_store.release_email_submission(
                        offer_id,
                        target_id,
                        lambda target_id=target_id: store.has_cancelled_mail_projection(
                            target_id
                        ),
                    )
                store.finish_cancelled_mail_projection(target_id)
                continue
            if offer_id:
                hw_store.confirm(
                    offer_id,
                    channel="email-auto",
                    note="Candidature envoyée par email",
                    applied_at=target["emailed_at"],
                    proof_kind="smtp_accepted",
                    proof_reference=target_id,
                )
                if hw_store.get(offer_id) is None:
                    raise ValueError("Offre de la candidature envoyée introuvable")
                hw_store.release_email_submission(offer_id, target_id)
            url = target["url"] or f"mailto:{target['email']}"
            suivi.record_application(
                url,
                campaign=target["campaign"],
                title=target.get("title") or "",
                company=target["name"],
                city=target["city"],
                source=target["detail"],
                applied_at=target["emailed_at"],
                lookup_distance=False,
            )
            store.finish_mail_projection(target_id)
        except Exception as exc:
            warnings.append(f"Suivi de l'envoi à réconcilier ({type(exc).__name__}).")


def _flush_mail_queue(
    env: dict[str, str], pdf_paths: dict[str, Path], warnings: list[str]
) -> list[dict]:
    """Envoie les candidatures en attente dans mail_queue en respectant les plafonds quotidiens."""
    from hellowork import store as hw_store

    _reconcile_mail_projections(warnings)
    emailed: list[dict] = []
    for target in store.pending_email():
        cap = JOB_CAP if target["campaign"] == "job" else STAGE_CAP
        if (
            store.sent_today() >= GLOBAL_CAP
            or store.sent_today(target["campaign"]) >= cap
        ):
            continue
        cv_to_send = pdf_paths[target["campaign"]]
        hw_offer_id = _mail_offer_id(target)
        if hw_offer_id:
            try:
                hw_store.init()
                current_offer = hw_store.get(hw_offer_id)
                if not current_offer:
                    raise ValueError("offre HelloWork introuvable")
                if current_offer["status"] in {
                    "applied",
                    "replied",
                    "interview",
                    "ignored",
                    "submission_unknown",
                    "submission_pending",
                    "to_finish",
                } or hw_store.has_application(hw_offer_id):
                    raise ValueError("candidature déjà traitée ou résultat à vérifier")
                if target["campaign"] == "stage":
                    from hellowork.cv_personalize import pdf_page_count

                    saved_kit = hw_store.kit_for(hw_offer_id)
                    kit_cv = (
                        Path(saved_kit["cv_path"])
                        if saved_kit and saved_kit.get("cv_path")
                        else None
                    )
                    if (
                        not saved_kit
                        or not hw_store.kit_is_current(hw_offer_id, saved_kit)
                        or not kit_cv
                        or not kit_cv.is_file()
                        or "stage-personnalise" not in kit_cv.name.casefold()
                        or pdf_page_count(kit_cv) != 1
                    ):
                        raise ValueError(
                            "CV de stage personnalisé absent ou dossier périmé"
                        )
                    cv_to_send = kit_cv
            except Exception as exc:
                warnings.append(
                    f"Dossier à vérifier pour {target['name']} ({type(exc).__name__}) : email conservé en file."
                )
                continue
        subject, body = _outgoing(target)
        if hw_offer_id:
            # La préparation peut être lente : relire après génération, avant la réservation SMTP.
            current_offer = hw_store.get(hw_offer_id)
            if (
                not current_offer
                or current_offer["status"] not in {"new", "shortlist", "prepared"}
                or hw_store.has_application(hw_offer_id)
            ):
                warnings.append(
                    f"Suivi modifié pour {target['name']} : email conservé en file."
                )
                continue
            if target["campaign"] == "stage" and not hw_store.kit_documents_current(
                saved_kit, body
            ):
                warnings.append(
                    f"Documents ou profil à revalider pour {target['name']} : email conservé en file."
                )
                continue
        try:
            attachment_bytes = cv_to_send.read_bytes()
            attachment_hash = hashlib.sha256(attachment_bytes).hexdigest()

            def reserve_mail(
                target=target,
                hw_offer_id=hw_offer_id,
                subject=subject,
                cap=cap,
                cv_to_send=cv_to_send,
                attachment_hash=attachment_hash,
            ) -> bool:
                return store.claim_new_email(
                    {**target, "hw_offer_id": hw_offer_id},
                    subject,
                    global_cap=GLOBAL_CAP,
                    campaign_cap=cap,
                    attachment_path=str(cv_to_send),
                    attachment_hash=attachment_hash,
                )

            reserved = (
                hw_store.reserve_email_submission(
                    hw_offer_id, target["key"], reserve_mail
                )
                if hw_offer_id
                else reserve_mail()
            )
            if not reserved:
                continue
            mailer.send(
                env["GMAIL_APP_PASSWORD"],
                target["email"],
                subject,
                body,
                cv_to_send,
                attachment_bytes=attachment_bytes,
            )
            store.mark_emailed(target["key"], subject)
            emailed.append(target)
        except Exception as exc:
            warnings.append(
                f"Envoi à vérifier pour {target['name']} ({type(exc).__name__}) : python main.py --pending-mails"
            )
            continue
    if emailed:
        _reconcile_mail_projections(warnings)
    return emailed


def _report_crash(env: dict[str, str], detail: str) -> None:
    write_private_text(DATA_DIR / "last-error.txt", detail)
    password = env.get("GMAIL_APP_PASSWORD")
    recipient = str(env.get("GMAIL_ADDRESS") or "").strip()
    if not password or not recipient:
        return
    try:
        mailer.send(
            password,
            recipient,
            "Script candidatures en erreur",
            "La recherche du matin s'est arrêtée. Si un envoi a été interrompu, "
            "vérifie les messages envoyés Gmail puis lance python main.py --pending-mails.\n\n"
            + detail[:3500],
            None,
        )
    except Exception:
        return


def _outgoing(target: dict) -> tuple[str, str]:
    """Enregistre la lettre de l'annonce avant tout envoi."""
    try:
        offer_letters.save(target)
    except Exception:
        pass
    saved = offer_letters.load(target.get("url") or "") or {}
    subject = str(saved.get("subject") or "")
    letter = str(saved.get("letter") or "")
    if subject and letter and offer_letters.validation_is_current(saved):
        return subject, letter
    return letters.message_for(target["campaign"], target["name"])


def _fresh(targets: list[dict]) -> list[dict]:
    fresh = []
    pass_links = {
        row["url"] for row in suivi.list_rows() if row.get("source") == "pass"
    }
    for target in targets:
        if not filters.keep(target, target["campaign"]):
            continue
        if target.get("source") == "pass" and target.get("url") in pass_links:
            continue
        if store.get_target(target["key"]) or store.is_queued(target["key"]):
            continue
        fresh.append(target)
    return fresh


def _gather(
    env: dict[str, str],
    days: int,
    warnings: list[str],
    *,
    skip_public_ats: bool = False,
) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    cfg = candidate_config.get_profile()
    active_contracts = set(cfg.contracts)
    alt_queries = [
        q.replace("stage ", "alternance ", 1)
        if q.lower().startswith("stage ")
        else f"alternance {q}"
        for q in ADZUNA_STAGE_QUERIES
    ]
    queries = {
        "job": ADZUNA_JOB_QUERIES,
        "stage": ADZUNA_STAGE_QUERIES,
        "alternance": alt_queries,
    }
    if adzuna.enabled(env):
        adzuna.reset_circuit()
        try:
            for campaign, zones in ZONES.items():
                if campaign not in active_contracts:
                    continue
                for zone in zones:
                    for query in queries.get(campaign, ()):
                        if adzuna.circuit_open():
                            break
                        for offer in adzuna.search(
                            env, query, zone["name"], days, zone["km"]
                        ):
                            _add(found, seen, offer, campaign, zone)
            if adzuna.circuit_open():
                warnings.append(
                    "Adzuna temporairement en retrait après des échecs répétés."
                )
        except Exception as exc:
            warnings.append(f"Adzuna indisponible ({type(exc).__name__}).")
    if "job" in active_contracts and jooble.enabled(env) and ZONES.get("job"):
        try:
            for zone in ZONES["job"]:
                for query in JOOBLE_JOB_QUERIES:
                    for offer in jooble.search(env, query, zone["name"], zone["km"]):
                        _add(found, seen, offer, "job", zone)
        except Exception as exc:
            warnings.append(f"Jooble indisponible ({type(exc).__name__}).")
    if offres.enabled(env):
        try:
            for campaign, zones in ZONES.items():
                if campaign not in active_contracts:
                    continue
                for zone in zones:
                    for query in queries.get(campaign, ()):
                        for offer in offres.search(env, query, zone):
                            _add(found, seen, offer, campaign, zone)
        except Exception as exc:
            warnings.append(f"France Travail indisponible ({type(exc).__name__}).")
    if lba.enabled(env, contracts=cfg.contracts):
        try:
            alt_zones = ZONES.get("alternance") or ZONES.get("stage") or []
            for zone in alt_zones:
                for offer in lba.search(env, zone, romes=STAGE_ROME_FALLBACK):
                    _add(found, seen, offer, "alternance", zone)
        except Exception as exc:
            warnings.append(f"La Bonne Alternance indisponible ({type(exc).__name__}).")
    if "stage" in active_contracts:
        try:
            for offer in pass_offres.search():
                for zone in ZONES.get("stage", ()):
                    _add(found, seen, offer, "stage", zone)
        except Exception as exc:
            warnings.append(f"PASS indisponible ({type(exc).__name__}).")
        if wttj.enabled(env):
            try:
                for zone in ZONES.get("stage", ()):
                    for offer in wttj.search(zone):
                        _add(found, seen, offer, "stage", zone)
            except Exception as exc:
                warnings.append(f"WTTJ indisponible ({type(exc).__name__}).")
        if apec.enabled(env):
            try:
                for zone in ZONES.get("stage", ()):
                    for offer in apec.search(zone):
                        _add(found, seen, offer, "stage", zone)
            except Exception as exc:
                warnings.append(f"APEC indisponible ({type(exc).__name__}).")
    _gather_extra_sources(
        found,
        seen,
        env,
        warnings,
        active_contracts=active_contracts,
        skip_public_ats=skip_public_ats,
    )
    if (
        not adzuna.enabled(env)
        and not jooble.enabled(env)
        and not offres.enabled(env)
        and not lba.enabled(env, contracts=cfg.contracts)
        and not wttj.enabled(env)
        and not apec.enabled(env)
        and not smartrecruiters.enabled(env)
        and not workday.enabled(env)
        and not csp_offres.enabled(env)
        and not teamtailor.enabled(env)
        and not recruitee.enabled(env)
        and not mail_alerts.enabled(env)
    ):
        warnings.append("Aucune source d'annonces n'est configurée.")
    return found


def _gather_extra_sources(
    found: list[dict],
    seen: set[str],
    env: dict[str, str],
    warnings: list[str],
    *,
    active_contracts: set[str] | None = None,
    skip_public_ats: bool = False,
) -> None:
    allowed = active_contracts if active_contracts is not None else {"job", "stage"}
    if not skip_public_ats:
        specs = (
            (
                "SmartRecruiters",
                smartrecruiters.enabled(env),
                lambda c: smartrecruiters.search(env, campaign=c),
                ("job", "stage", "alternance"),
            ),
            (
                "Workday",
                workday.enabled(env),
                lambda c: workday.search(env, campaign=c),
                ("stage", "job", "alternance"),
            ),
            (
                "Choisir le Service Public",
                csp_offres.enabled(env),
                lambda c: csp_offres.search(env, campaign=c),
                ("stage", "alternance"),
            ),
            (
                "Teamtailor",
                teamtailor.enabled(env),
                lambda c: teamtailor.search(env, campaign=c),
                ("stage", "job", "alternance"),
            ),
            (
                "Recruitee",
                recruitee.enabled(env),
                lambda c: recruitee.search(env, campaign=c),
                ("stage", "job", "alternance"),
            ),
        )
        for label, active, fetcher, campaigns in specs:
            if not active:
                continue
            try:
                for campaign in campaigns:
                    if campaign not in allowed:
                        continue
                    for offer in fetcher(campaign):
                        for zone in ZONES.get(campaign, ()):
                            _add(found, seen, offer, campaign, zone)
            except Exception as exc:
                warnings.append(f"{label} indisponible ({type(exc).__name__}).")

    if mail_alerts.enabled(env):
        try:
            for offer in mail_alerts.search(env):
                campaign = "stage" if offer.get("contract_type") == "stage" else "job"
                if campaign not in allowed:
                    continue
                for zone in ZONES.get(campaign, ()):
                    _add(found, seen, offer, campaign, zone)
        except Exception as exc:
            warnings.append(
                f"Alertes mail externes indisponibles ({type(exc).__name__})."
            )


def _add(
    found: list[dict], seen: set[str], raw: dict, campaign: str, zone: dict
) -> None:
    item = dict(raw)
    item["campaign"] = campaign
    item["origin_lat"] = zone["lat"]
    item["origin_lon"] = zone["lon"]
    if not filters.keep(item, campaign):
        return
    email = (raw.get("email") or "").strip()
    if email:
        title_norm = filters._fold(raw.get("title") or "")
        key = f"{email.lower()}|{campaign}|{title_norm}"
    else:
        identity = raw.get("id") or raw.get("url") or raw.get("name")
        key = f"{identity}".lower()
    duplicate = filters.same_offer(
        campaign, raw.get("name") or "", raw.get("title") or ""
    )
    if not key or key in seen or duplicate in seen:
        return
    seen.add(key)
    seen.add(duplicate)
    item["key"] = key
    item["email"] = email
    found.append(item)


def _remember(target: dict, kind: str) -> None:
    store.upsert_seen(
        target["key"],
        target["campaign"],
        target["name"],
        target.get("email") or "",
        target.get("url") or "",
        target.get("city") or "",
        target.get("source") or "",
    )
    if kind == "digest":
        store.mark_digest(target["key"])


def _relances(
    env: dict[str, str], pdf_paths: dict[str, Path], warnings: list[str]
) -> tuple[list[str], list[str]]:
    relanced: list[str] = []
    replies: list[str] = []
    due = store.due_relances()
    if not due:
        return relanced, replies
    try:
        previously_relanced = {
            suivi._norm_link(row["url"])
            for row in suivi.list_rows()
            if row["status"] == "Relancé"
        }
    except Exception as exc:
        warnings.append(
            f"Lecture du suivi impossible ({type(exc).__name__}). Relances suspendues."
        )
        return relanced, replies
    for row in due:
        target = dict(row)
        url = row["url"] or f"mailto:{row['email']}"
        if suivi._norm_link(url) in previously_relanced:
            continue
        if store.sent_today() >= GLOBAL_CAP:
            break
        try:
            if mailer.has_reply(
                env["GMAIL_APP_PASSWORD"], row["email"], since=row["emailed_at"]
            ):
                store.mark_replied(row["id"])
                replies.append(f"{row['name']} <{row['email']}>")
                try:
                    import notifier

                    notifier.notify_recruiter_reply(
                        row["name"], "Réponse reçue", f"Email: {row['email']}"
                    )
                except Exception:
                    pass
                continue
        except Exception as exc:
            warnings.append(
                f"Lecture des réponses impossible ({type(exc).__name__}). Relances suspendues."
            )
            break
        attachment = pdf_paths[row["campaign"]]
        attachment_bytes = None
        if target["campaign"] == "stage" and (
            _mail_offer_id(target) or target.get("attachment_hash")
        ):
            try:
                attachment = Path(target["attachment_path"] or "")
                attachment_bytes = attachment.read_bytes()
                if (
                    hashlib.sha256(attachment_bytes).hexdigest()
                    != target["attachment_hash"]
                ):
                    raise ValueError("CV différent du document initial")
            except (ValueError, OSError):
                warnings.append(
                    f"CV initial indisponible pour {row['name']} : relance à préparer manuellement."
                )
                continue
        subject, body = letters.relance(row["name"], row["campaign"])
        if not store.mark_relance_unknown(row["id"], global_cap=GLOBAL_CAP):
            continue
        try:
            mailer.send(
                env["GMAIL_APP_PASSWORD"],
                row["email"],
                subject,
                body,
                attachment,
                attachment_bytes=attachment_bytes,
            )
            store.mark_relanced(row["id"])
            relanced.append(row["name"])
        except Exception as exc:
            warnings.append(
                f"Relance à vérifier pour {row['name']} ({type(exc).__name__}) : python main.py --pending-mails"
            )
    return relanced, replies


def _catchup_days() -> int:
    # Un chevauchement de trois jours évite de manquer une annonce publiée ou
    # indexée tardivement ; les identifiants stockés évitent les doubles envois.
    return 3


def _summary(
    emailed: list[dict],
    digest: list[dict],
    relanced: list[str],
    replies: list[str],
    warnings: list[str],
) -> str:
    lines = ["Récap du matin", ""]
    if replies:
        lines.append("Réponses à traiter aujourd'hui :")
        lines.extend(f"- {item}" for item in replies)
        lines.append("")
    lines.append(f"Mails partis : {len(emailed)}")
    for item in emailed:
        lines.append(f"- {item['campaign']} — {item['name']} — {item['email']}")
    if relanced:
        lines.append("")
        lines.append("Relances :")
        lines.extend(f"- {name}" for name in relanced)
    lines.append("")
    lines.append(f"Liens à ouvrir (pas d'email) : {len(digest)}")
    for item in digest:
        link = item.get("url") or item.get("phone") or "sans lien"
        lines.append(
            f"- {item['campaign']} — {item['name']} ({item.get('city') or ''}) — {link}"
        )
    if warnings:
        lines.append("")
        lines.append("Notes :")
        lines.extend(f"- {item}" for item in warnings)
    return "\n".join(lines) + "\n"


def _print_dry(fresh: list[dict], warnings: list[str], days: int) -> None:
    with_mail = [item for item in fresh if item.get("email")]
    links = [item for item in fresh if not item.get("email")]
    print(f"Dry-run. Annonces sur {days} jour(s). Aucun mail envoyé.")
    print(f"Prêts à envoyer : {len(with_mail)} — liens seulement : {len(links)}")
    for item in with_mail[:30]:
        print(f"  MAIL {item['campaign']} — {item['name']} — {item['email']}")
    for item in links[:30]:
        print(
            f"  LIEN {item['campaign']} — {item['name']} — {item.get('url') or item.get('phone') or 'sans contact'}"
        )
    for item in warnings:
        print(f"NOTE {item}")


if __name__ == "__main__":
    raise SystemExit(main())

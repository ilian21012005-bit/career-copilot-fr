"""Relances recruteur uniquement lorsqu'un mail direct existe.

HelloWork, Jooble, Adzuna, France Travail, WTTJ, APEC et PASS n'offrent aucun
moyen de relancer. Ces candidatures restent suivies, sans échéance J+7.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

import candidate_config
import store as mail_store
import suivi
from config import GMAIL_ADDRESS, SENDER_NAME

logger = logging.getLogger(__name__)

_FRENCH_MONTHS: tuple[str, ...] = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)

PORTAILS_SANS_RELANCE = frozenset(
    {
        "hellowork",
        "jooble",
        "adzuna",
        "francetravail",
        "wttj",
        "apec",
        "pass",
    }
)


def _profile_links(candidate: Mapping[str, Any] | None = None) -> str:
    cand = (
        candidate if candidate is not None else candidate_config.get_profile().candidate
    )
    links: list[str] = []
    for key, label, host in (
        ("linkedin_url", "LinkedIn", "linkedin.com"),
        ("github_url", "GitHub", "github.com"),
    ):
        value = str(cand.get(key) or "").strip()
        parsed = urlparse(value)
        valid_hosts = {host, f"www.{host}"}
        if (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() in valid_hosts
            and not parsed.username
            and not parsed.password
        ):
            links.append(f"{label}: {value}")
    portfolio = str(cand.get("portfolio_url") or "").strip()
    if portfolio:
        parsed_p = urlparse(portfolio)
        if (
            parsed_p.scheme == "https"
            and parsed_p.hostname
            and "." in parsed_p.hostname
            and not parsed_p.username
            and not parsed_p.password
        ):
            links.append(f"Portfolio: {portfolio}")
    return " | ".join(links)


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date) and type(value) is date:
        return value
    if isinstance(value, str):
        return parse_date(value)
    return None


def _format_french_date(value: Any) -> str:
    parsed = _coerce_date(value)
    if parsed is None:
        return ""
    return f"{parsed.day} {_FRENCH_MONTHS[parsed.month - 1]} {parsed.year}"


def _format_stage_period(candidate: Mapping[str, Any]) -> str:
    start_d = _coerce_date(candidate.get("start"))
    end_d = _coerce_date(candidate.get("end"))
    raw_weeks = candidate.get("weeks")
    weeks_label = ""
    if isinstance(raw_weeks, int) and not isinstance(raw_weeks, bool) and raw_weeks > 0:
        weeks_label = f" ({raw_weeks} semaines, temps plein)"

    if start_d and end_d:
        m_start = _FRENCH_MONTHS[start_d.month - 1]
        m_end = _FRENCH_MONTHS[end_d.month - 1]
        if start_d.year == end_d.year:
            return f"du {start_d.day} {m_start} au {end_d.day} {m_end} {end_d.year}{weeks_label}"
        return f"du {start_d.day} {m_start} {start_d.year} au {end_d.day} {m_end} {end_d.year}{weeks_label}"
    if start_d:
        return f"à compter du {_format_french_date(start_d)}{weeks_label}"
    return f"pour la période prévue{weeks_label}"


def _build_education_intro(cfg: candidate_config.CandidateProfileConfig) -> str:
    cand = cfg.candidate
    level = str(cand.get("level") or "").strip()
    track = str(cand.get("track") or "").strip()
    school = str(cand.get("school") or "").strip()

    if level and track and school:
        return f"Actuellement en {level} ({track}, {school})"
    if level and school:
        return f"Actuellement en {level} ({school})"
    if level and track:
        return f"Actuellement en {level} ({track})"
    if level:
        return f"Actuellement en {level}"
    if school:
        return f"Actuellement en formation supérieure ({school})"
    return f"Actuellement en formation supérieure ({cfg.preset.label})"


def _lookup_answer(answers: Mapping[str, str], keys: tuple[str, ...]) -> str:
    lowered_map = {
        str(k).strip().lower(): str(v).strip()
        for k, v in answers.items()
        if str(v).strip()
    }
    for key in keys:
        val = lowered_map.get(key.lower(), "")
        if val:
            return val
    return ""


def _sanitize_relance_text(text: str) -> str:
    cleaned = text.replace("chaque samedi", "le week-end").replace(
        "Chaque samedi", "Le week-end"
    )
    cleaned = cleaned.replace("pièce jointe", "dossier de candidature").replace(
        "Pièce jointe", "Dossier de candidature"
    )
    return cleaned


def _build_signature(cfg: candidate_config.CandidateProfileConfig) -> tuple[str, str]:
    cand = cfg.candidate
    sender_name = str(cand.get("name") or "").strip() or SENDER_NAME
    sender_email = str(cand.get("email") or "").strip() or GMAIL_ADDRESS
    sender_phone = str(cand.get("phone") or "").strip()
    contact_line = " | ".join(part for part in (sender_phone, sender_email) if part)
    links_line = _profile_links(cand)
    lines = [sender_name]
    if contact_line:
        lines.append(contact_line)
    if links_line:
        lines.append(links_line)
    return sender_name, "\n".join(lines)


def adresse_relance(email: str = "", url: str = "") -> str:
    raw = (email or "").strip()
    if not raw and (url or "").lower().startswith("mailto:"):
        raw = urllib.parse.unquote(url.split(":", 1)[1].split("?", 1)[0]).strip()
    return raw


def relance_possible(*, source: str = "", url: str = "", email: str = "") -> bool:
    """Vrai seulement pour un mail de recruteur, jamais pour un portail de candidature."""
    if suivi.source_name(url, source) in PORTAILS_SANS_RELANCE:
        return False
    address = adresse_relance(email, url).lower()
    if "@" not in address or " " in address:
        return False
    return not any(
        marker in address for marker in ("noreply", "no-reply", "donotreply")
    )


def parse_date(date_str: str | None) -> date | None:
    """Tente de parser diverses représentations de dates (ISO, YYYY-MM-DD, etc.)."""
    if not date_str:
        return None
    raw = str(date_str).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _collect_hellowork_applied(today: date) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        from hellowork import store as hw_store

        hw_store.init()
        with hw_store._db() as conn:
            apps = conn.execute(
                "SELECT * FROM applications ORDER BY applied_at DESC"
            ).fetchall()
            for row in apps:
                r = dict(row)
                if r.get("status") not in ("sent", "applied"):
                    continue
                d = parse_date(r.get("applied_at"))
                delta = (today - d).days if d else None
                relanced = bool(
                    r.get("offer_id")
                    and conn.execute(
                        "SELECT 1 FROM events WHERE kind = 'relanced' AND offer_id = ? AND at >= ? LIMIT 1",
                        (r["offer_id"], r.get("applied_at") or ""),
                    ).fetchone()
                )
                possible = relance_possible(
                    source="hellowork", email=str(r.get("email") or "")
                )
                results.append(
                    {
                        "id": str(r.get("offer_id") or r.get("id")),
                        "url": "",
                        "title": r.get("title") or "Candidature",
                        "company": r.get("company") or "Entreprise",
                        "applied_date": d.isoformat() if d else "",
                        "days_elapsed": delta,
                        "can_follow_up": possible,
                        "is_due": possible
                        and delta is not None
                        and delta >= 7
                        and not relanced,
                        "status": "Relancé" if relanced else "Suivie",
                        "source": "hellowork",
                        "email": str(r.get("email") or ""),
                        "is_stage": True,
                    }
                )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erreur lecture candidatures HelloWork pour relances : %s", exc)
    return results


def _load_mail_targets() -> tuple[
    dict[str, dict[str, Any] | None], dict[tuple[str, str], dict[str, Any] | None]
]:
    by_url: dict[str, dict[str, Any] | None] = {}
    by_pair: dict[tuple[str, str], dict[str, Any] | None] = {}
    try:
        with mail_store._connect() as conn:
            for row in conn.execute(
                """SELECT t.*, q.payload AS queue_payload FROM targets t
                   LEFT JOIN mail_queue q ON q.target_id = t.id WHERE t.email != ''"""
            ):
                target = dict(row)
                if not target.get("title") and target["queue_payload"]:
                    try:
                        target["title"] = json.loads(target["queue_payload"]).get(
                            "title", ""
                        )
                    except (ValueError, AttributeError):
                        pass
                t_url = str(target["url"] or "").strip() or f"mailto:{target['email']}"
                by_url[t_url] = target if t_url not in by_url else None
                t_pair = (
                    str(target["name"] or "").strip().lower(),
                    str(target.get("title") or "").strip().lower(),
                )
                if all(t_pair):
                    by_pair[t_pair] = target if t_pair not in by_pair else None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Lecture des adresses et états de relance indisponible (%s)",
            type(exc).__name__,
        )
    return by_url, by_pair


def _collect_suivi_applied(today: date) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    try:
        mail_targets_by_url, mail_targets_by_pair = _load_mail_targets()
        rows = suivi.list_rows()
        for r in rows:
            st = (r.get("status") or "").strip()
            app = (r.get("applied") or "").strip().lower()
            if not (app == "oui" or st in ("Postulé", "Transmise", "Relancé")):
                continue
            source = str(r.get("source") or "")
            url = str(r.get("url") or "")
            pair = (
                str(r.get("company") or "").strip().lower(),
                str(r.get("title") or "").strip().lower(),
            )
            target = (
                mail_targets_by_url.get(url) if url else mail_targets_by_pair.get(pair)
            ) or {}
            d = parse_date(r.get("applied_date") or target.get("emailed_at"))
            delta = (today - d).days if d else None
            is_relanced = st == "Relancé" or bool(
                target.get("relanced_at") or target.get("manual_relanced_at")
            )
            is_blocked = target.get("status") in ("relance_unknown", "replied")
            pair_target = mail_targets_by_pair.get(pair) or {}
            raw_email = str(
                r.get("email") or target.get("email") or pair_target.get("email") or ""
            ).strip()
            email = adresse_relance(raw_email, url)
            possible = relance_possible(source=source, url=url, email=email)
            raw_type = (r.get("type") or "").lower()
            results.append(
                {
                    "id": "",
                    "url": url,
                    "title": r.get("title") or "Candidature",
                    "company": r.get("company") or "Entreprise",
                    "city": r.get("city") or "",
                    "applied_date": d.isoformat() if d else "",
                    "days_elapsed": delta,
                    "can_follow_up": possible and not is_relanced and not is_blocked,
                    "is_due": possible
                    and delta is not None
                    and delta >= 7
                    and not is_relanced
                    and not is_blocked,
                    "status": "Relancé" if is_relanced else st or "Postulé",
                    "source": source or "web",
                    "email": email if possible else "",
                    "type": str(r.get("type") or ""),
                    "is_alternance": "alternance" in raw_type,
                    "is_stage": "stage" in raw_type,
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erreur lecture suivi pour relances : %s", exc)
    return results


def get_applied_candidates() -> list[dict[str, Any]]:
    """Récupère l'ensemble des candidatures transmises depuis HelloWork et le suivi multi-sources."""
    today = date.today()
    return _collect_hellowork_applied(today) + _collect_suivi_applied(today)


def _resolve_contract_kind(item: Mapping[str, Any]) -> str:
    raw_type = str(item.get("type") or "").strip().lower()
    if bool(item.get("is_alternance")) or "alternance" in raw_type:
        return "alternance"
    if "is_stage" in item:
        return "stage" if bool(item.get("is_stage")) else "job"
    if "job" in raw_type:
        return "job"
    return "stage"


def generate_relance(item: dict[str, Any]) -> dict[str, str]:
    """Prépare un mailto vers le recruteur en lisant `candidate_config.get_profile()` à chaud."""
    email = adresse_relance(str(item.get("email") or ""), str(item.get("url") or ""))
    if not relance_possible(
        source=str(item.get("source") or ""),
        url=str(item.get("url") or ""),
        email=email,
    ):
        raise ValueError("Ce site ne permet pas de relancer : aucun mail de recruteur")

    cfg = candidate_config.get_profile()
    title = (item.get("title") or "ce poste").strip()
    company = (item.get("company") or "votre entreprise").strip()
    app_date_str = item.get("applied_date") or ""
    contract_kind = _resolve_contract_kind(item)

    date_label = "récemment"
    if app_date_str:
        parsed = parse_date(app_date_str)
        if parsed:
            date_label = f"le {parsed.strftime('%d/%m/%Y')}"

    edu_intro = _build_education_intro(cfg)
    sender_name, signature = _build_signature(cfg)

    if contract_kind == "alternance":
        dispo_alt = _sanitize_relance_text(
            _lookup_answer(
                cfg.form_answers,
                ("rythme", "alternance", "disponibilité", "disponibilite"),
            )
        )
        start_str = _format_french_date(cfg.candidate.get("start"))
        if dispo_alt:
            alt_timing = f"disponible en alternance ({dispo_alt})"
        elif start_str:
            alt_timing = f"disponible pour un contrat d'alternance dès le {start_str}"
        else:
            alt_timing = "disponible pour un contrat d'alternance"

        subject = f"Candidature alternance – {title} – {sender_name}"
        body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de revenir vers vous concernant ma candidature transmise {date_label} "
            f"pour le poste en alternance de {title} au sein de {company}.\n\n"
            f"{edu_intro}, je réitère mon vif intérêt pour rejoindre vos équipes, {alt_timing}.\n\n"
            f"Je reste à votre entière disposition pour convenir d'un court échange téléphonique ou visio "
            f"afin de vous présenter mon parcours et mes motivations.\n\n"
            f"Je vous remercie par avance pour l'attention portée à ma démarche et vous prie d'agréer, "
            f"Madame, Monsieur, l'expression de mes salutations distinguées.\n\n"
            f"{signature}\n"
        )
    elif contract_kind == "stage":
        period = _format_stage_period(cfg.candidate)
        subject = f"Candidature stage – {title} – {sender_name}"
        body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de revenir vers vous concernant ma candidature transmise {date_label} "
            f"pour le stage de {title} au sein de {company}.\n\n"
            f"{edu_intro}, je réitère mon vif intérêt pour rejoindre vos équipes {period}.\n\n"
            f"Je reste motivé par les missions de ce stage et serais heureux de vous présenter mon parcours.\n\n"
            f"Je reste à votre entière disposition pour convenir d'un court échange téléphonique ou visio "
            f"afin de vous exposer mes motivations.\n\n"
            f"Je vous remercie par avance pour l'attention portée à ma démarche et vous prie d'agréer, "
            f"Madame, Monsieur, l'expression de mes salutations distinguées.\n\n"
            f"{signature}\n"
        )
    else:
        job_dispo = _sanitize_relance_text(
            _lookup_answer(
                cfg.job_form_answers,
                ("disponibilité", "disponibilite", "horaires", "planning"),
            )
        )
        job_mob = _sanitize_relance_text(
            _lookup_answer(cfg.job_form_answers, ("mobilité", "mobilite"))
        )
        if job_dispo:
            dispo_text = f"disponible dès maintenant ({job_dispo})"
        else:
            dispo_text = (
                "disponible dès maintenant à temps partiel (week-ends, soirs) "
                "ainsi que pendant les vacances scolaires"
            )
        if job_mob:
            dispo_text = f"{dispo_text}, mobile sur {job_mob}"

        subject = f"Candidature job étudiant – {title} – {sender_name}"
        body = (
            f"Madame, Monsieur,\n\n"
            f"Je me permets de faire suite à ma candidature déposée {date_label} "
            f"pour le poste de {title} chez {company}.\n\n"
            f"{edu_intro}, je suis {dispo_text}.\n\n"
            f"Je serais ravi de vous rencontrer lors d'un entretien pour vous présenter ma motivation.\n\n"
            f"Bien cordialement,\n\n"
            f"{signature}"
        )

    body = _sanitize_relance_text(body)
    mailto_params = urllib.parse.urlencode(
        {
            "subject": subject,
            "body": body,
        }
    )
    mailto_url = f"mailto:{urllib.parse.quote(email, safe='@')}?{mailto_params}"

    return {
        "subject": subject,
        "body": body,
        "mailto": mailto_url,
    }


def mark_as_relanced(url: str = "", offer_id: str = "") -> bool:
    """Met à jour le statut de l'offre à 'Relancé'."""
    updated = False
    if url:
        try:
            mail_store.init()
            shared = mail_store.mark_manual_relance(url, adresse_relance(url=url))
            if shared is False:
                return False
            updated = shared is True
            updated = suivi.update_row(url, status="Relancé") or updated
        except Exception:
            logger.exception("Échec de la mise à jour de la relance")

    if offer_id:
        try:
            from hellowork import store as hw_store

            hw_store.init()
            row = hw_store.get(offer_id)
            note = f"Relancé le {date.today().isoformat()}"
            if (
                row and row["status"] in ("interview", "replied")
            ) or hw_store.set_status(offer_id, "applied", note=note):
                hw_store.event("relanced", offer_id, "Relance J+7 effectuée")
                updated = True
        except Exception:
            logger.exception("échec mise à jour relance HelloWork %s", offer_id)

    return updated

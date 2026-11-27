"""Analyse profonde : teaser HelloWork + page partenaire (Apec / ATS).

Ne juge plus une offre sur la preview seule. Pour chaque fiche :

1. détecte le mode (HelloWork natif vs partenaire) ;
2. récupère le texte partenaire (lien HTML, match Apec, page_fetch) ;
3. fusionne + re-score (durée 6 mois, école d'ingé, etc.) ;
4. pose `apply_capability` :
   - `auto_hellowork` → automatisable via Playwright HelloWork ;
   - `manual_partner` → tu candidatures sur le site partenaire ;
   - `manual_other` → Indeed/LinkedIn/PASS/autre ;
   - `unknown` → pas encore enrichi.

Aucun envoi ici. Idempotent, délai entre requêtes, plafond/run.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

from . import ats_alive, geo, offer as offers, profile, score as scoring, store
from .offer import Offer
from .text import fold

LOG = logging.getLogger("hellowork.partner_deep")
PAGES = Path(__file__).resolve().parents[1] / "data" / "hellowork" / "pages"
PARTNER_MARK = "\n\n--- PAGE PARTENAIRE ---\n\n"
MAX_PER_RUN = 30
DELAY_SEC = 1.2
_HOST_LAST_FETCH: dict[str, float] = {}
_HOST_LOCK = threading.Lock()


_POLLUTED_PARTNER_MARKERS = (
    "apps.apple.com",
    "play.google.com",
    "clubmedjobs.com",
    "account.wizbii.com",
    "utm_campaign=poweredby",
    "customer-success-stories",
    "app.teamtailor.com/login",
)


def _sanitize_partner_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw.startswith(("http://", "https://")):
        return ""
    if "&q;" in raw:
        raw = raw.split("&q;", 1)[0]
    if "&quot;" in raw:
        raw = raw.split("&quot;", 1)[0]
    low = raw.lower()
    if any(marker in low for marker in _POLLUTED_PARTNER_MARKERS):
        return ""
    return raw


def _rate_limit_host(
    url: str,
    delay: float | None = None,
    *,
    sleep=None,
    monotonic=None,
) -> float:
    """Applique le délai minimal par hôte sans bloquer les requêtes vers d'autres hôtes."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    if not host:
        return 0.0
    min_delay = DELAY_SEC if delay is None else float(delay)
    if min_delay <= 0:
        return 0.0
    sleep_fn = time.sleep if sleep is None else sleep
    mono_fn = time.monotonic if monotonic is None else monotonic

    with _HOST_LOCK:
        now = mono_fn()
        last = _HOST_LAST_FETCH.get(host)
        wait = 0.0 if last is None else max(0.0, (last + min_delay) - now)
        _HOST_LAST_FETCH[host] = now + wait
    if wait > 0:
        sleep_fn(wait)
    return wait

def _partner_text_ok(text: str) -> bool:
    """Refuse cookie walls / App Store / pages vides déguisées."""
    t = (text or "").strip()
    if len(t) < 350:
        return False
    low = t.lower()
    head = low[:1200]
    hard_junk = (
        "respects your privacy",
        "confirm you are human",
        "complete the security check",
        "apps | arcade",
        "aujourd'hui | jeux | apps",
        "jeux | apps | arcade",
        "sign in to linkedin",
        "club med est faite pour vous",
        "faisons connaissance !",
        "this page isn't working",
        "http error 400",
    )
    if any(j in head for j in hard_junk):
        return False
    if "apps | arcade" in low or "jeux | apps" in low:
        return False
    # texte utile stage/cyber attendu pour listings enrichis
    useful = ("stage", "mission", "profil", "compétence", "cybers", "sécurité", "security", "internship", "postuler")
    if not any(u in low for u in useful):
        return False
    return True


def ensure_columns() -> None:
    store.init()
    with store._db() as conn:  # type: ignore[attr-defined]
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(offers)")}
        for name, kind in (
            ("partner_url", "TEXT"),
            ("apply_capability", "TEXT"),
            ("partner_checked_at", "TEXT"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE offers ADD COLUMN {name} {kind}")


def detect_response_type(html: str) -> str:
    """Classe le tunnel de candidature à partir du HTML de la fiche.

    HelloWork marque encore certaines candidatures natives `response_type: ATS`
    (CTA Postuler-FormRO + turbo-frame getinitialformframeview). Ce n'est pas
    un ATS externe : le formulaire CV + message reste sur hellowork.com.
    """
    folded = fold(html or "")
    if "postuler sur le site du partenaire" in folded or "postuler sur le site du recruteur" in folded:
        return "partner"
    # Funnel natif : SmartApply historique, FormRO actuel, frame d'apply.
    if (
        "smartapply" in folded
        or "postuler-formro" in folded
        or "getinitialformframeview" in folded
        or "offer-detail-funnel-container" in folded
    ):
        return "hellowork"
    if "urlwithform" in folded:
        return "partner"
    if "response_type\":\"ats\"" in folded or "response_type&quot;:&quot;ats" in folded:
        return "ats"
    return "unknown"


def apply_capability_for(response_type: str, url: str) -> str:
    host = urllib.parse.urlparse(url or "").hostname or ""
    if response_type == "hellowork" and "hellowork.com" in host:
        return "auto_hellowork"
    if response_type in ("partner", "ats"):
        return "manual_partner"
    if "hellowork.com" in host:
        return "unknown"
    return "manual_other"


def _page_cache_ids(offer_id: str, url: str = "") -> list[str]:
    ids: list[str] = []
    if offer_id:
        ids.append(offer_id)
    if url and offers.is_offer_page(url):
        numeric = offers.offer_id(url)
        if numeric and numeric not in ids:
            ids.append(numeric)
    return ids


def _cached_html(offer_id: str, url: str = "") -> str:
    for cache_id in _page_cache_ids(offer_id, url):
        path = PAGES / f"{cache_id}.html"
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return ""


def _load_html(offer: Offer) -> str:
    html = _cached_html(offer.id, offer.url)
    if html and len(html) > 2000:
        return html
    if "hellowork.com" not in (offer.url or ""):
        return html
    try:
        refreshed = offers.read(offer.url)
        offer.description = refreshed.description or offer.description
        offer.missions = refreshed.missions or offer.missions
        offer.profile = refreshed.profile or offer.profile
        offer.benefits = refreshed.benefits or offer.benefits
        return _cached_html(offer.id, offer.url)
    except Exception as exc:
        LOG.warning("Fiche HW illisible %s : %s", offer.id, exc)
        return html


def _strip_partner_block(text: str) -> str:
    if PARTNER_MARK in (text or ""):
        return text.split(PARTNER_MARK, 1)[0].rstrip()
    return text or ""


def _merge_partner_text(offer: Offer, partner_text: str) -> None:
    partner_text = re.sub(r"[ \t]+\n", "\n", partner_text).strip()
    if len(partner_text) < 200:
        return
    base = _strip_partner_block(offer.description)
    offer.description = base + PARTNER_MARK + partner_text
    if len(offer.profile or "") < 80:
        folded = fold(partner_text)
        for marker in ("profil recherche", "profil recherché", "vous etes", "vous êtes"):
            idx = folded.find(marker)
            if idx >= 0:
                # approx: take a window from original text
                offer.profile = partner_text[max(0, idx) : max(0, idx) + 2500]
                break


def _page_fetch(url: str) -> str:
    deep = _page_fetch_deep(url)
    # Prefer ATS body when richer than listing preview
    ats = deep.get("ats_text") or ""
    listing = deep.get("listing_text") or ""
    if len(ats) >= max(300, int(len(listing) * 0.6)):
        return ats
    return ats or listing


def _page_fetch_deep(url: str) -> dict:
    empty = {"listing_text": "", "ats_url": "", "ats_text": "", "final_url": "", "method": "none"}
    if not url.startswith("https://"):
        return empty
    try:
        import page_fetch

        if hasattr(page_fetch, "read_offer_deep"):
            return page_fetch.read_offer_deep(url) or empty
        text = page_fetch.read_offer(url) or ""
        return {
            "listing_text": text,
            "ats_url": "",
            "ats_text": "",
            "final_url": url,
            "method": "listing_only",
        }
    except Exception as exc:
        LOG.info("page_fetch_deep échec %s : %s", url, exc)
        return empty


_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def _iter_jsonld_nodes(payload: object):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_jsonld_nodes(item)
    elif isinstance(payload, dict):
        yield payload
        graph = payload.get("@graph")
        if graph is not None:
            yield from _iter_jsonld_nodes(graph)


def extract_jobposting_jsonld(html: str) -> dict[str, str]:
    """Extrait les métadonnées Schema.org JobPosting (description, email, lieu) d'une page HTML."""
    import html as html_lib

    for match in _JSONLD_RE.finditer(html or ""):
        raw_json = match.group(1).strip()
        if not raw_json:
            continue
        try:
            parsed = json.loads(raw_json)
        except ValueError:
            continue
        for node in _iter_jsonld_nodes(parsed):
            kind = node.get("@type")
            types = [str(kind)] if isinstance(kind, str) else [str(t) for t in (kind or [])] if isinstance(kind, list) else []
            if not any(t.lower().endswith("jobposting") for t in types):
                continue
            raw_desc = str(node.get("description") or "")
            desc = re.sub(r"<[^>]+>", " ", html_lib.unescape(raw_desc))
            desc = re.sub(r"\s+", " ", desc).strip()
            contact = node.get("applicationContact")
            email = ""
            if isinstance(contact, dict):
                email = str(contact.get("email") or "").strip()
            elif isinstance(node.get("email"), str):
                email = node["email"].strip()
            loc = node.get("jobLocation")
            city = ""
            if isinstance(loc, list) and loc:
                loc = loc[0]
            if isinstance(loc, dict):
                addr = loc.get("address")
                if isinstance(addr, dict):
                    city = str(addr.get("addressLocality") or "").strip()
            org = node.get("hiringOrganization")
            company = str(org.get("name") or "").strip() if isinstance(org, dict) else ""
            return {
                "title": str(node.get("title") or "").strip(),
                "company": company,
                "city": city,
                "description": desc[:6000],
                "email": email,
                "employment_type": str(node.get("employmentType") or "").strip(),
            }
    return {}


def _extract_external_urls(html: str) -> list[str]:
    urls: list[str] = []
    for m in re.finditer(r"https?://[^\s\"'<>]+", html or ""):
        u = m.group(0).rstrip(".,);]")
        host = (urllib.parse.urlparse(u).hostname or "").lower()
        if any(
            x in host
            for x in (
                "apec.fr",
                "smartrecruiters.com",
                "myworkdayjobs.com",
                "greenhouse.io",
                "lever.co",
                "welcometothejungle.com",
                "talent.com",
            )
        ):
            urls.append(u)
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:5]


def _fetch_apec_match(offer: Offer) -> tuple[str, str]:
    try:
        import apec
    except ImportError:
        return "", ""
    if not apec.enabled():
        return "", ""
    company = fold(offer.company)
    title_tokens = [
        t
        for t in re.findall(r"[a-z0-9+]{4,}", fold(offer.title))
        if t not in {"stage", "consultant", "ingenieure", "ingenieur"}
    ]
    try:
        pool = apec.get_cached_offers()
    except Exception as exc:
        LOG.warning("Apec indisponible : %s", exc)
        return "", ""

    best = None
    best_score = 0
    for item in pool:
        c = fold(str(item.get("name") or item.get("company") or ""))
        t = fold(str(item.get("title") or ""))
        score = 0
        if company and company in c:
            score += 3
        elif company and c and (company[:8] in c or c[:8] in company):
            score += 2
        score += sum(1 for tok in title_tokens if tok in t)
        if score > best_score:
            best_score = score
            best = item
    if not best or best_score < 4:
        return "", ""
    url = str(best.get("url") or "")
    text = str(best.get("description") or best.get("text") or "")
    if len(text) < 300 and url:
        text = _page_fetch(url) or text
    return url, text


def _capability_from_row(row) -> str:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    if "apply_capability" in keys and row["apply_capability"]:
        return str(row["apply_capability"])
    notes = row["notes"] or ""
    matches = re.findall(r"\[partner_deep\] (\{.*?\})", notes)
    if not matches:
        return "unknown"
    try:
        return json.loads(matches[-1]).get("apply_capability") or "unknown"
    except json.JSONDecodeError:
        return "unknown"


def enrich_offer(offer: Offer, *, force: bool = False) -> dict:
    ensure_columns()
    row = store.get(offer.id)
    if row and not force:
        if "[partner_deep]" in (row["notes"] or "") and (
            PARTNER_MARK in (row["description"] or "")
            or _capability_from_row(row) != "unknown"
        ):
            return {
                "id": offer.id,
                "skipped": True,
                "reason": "déjà enrichi",
                "apply_capability": _capability_from_row(row),
                "score": row["score"],
                "status": row["status"],
            }

    html = _load_html(offer) if "hellowork.com" in (offer.url or "") else ""
    if "hellowork.com" in (offer.url or ""):
        response_type = detect_response_type(html) if html else "unknown"
    else:
        response_type = "direct_source"

    if response_type == "direct_source":
        capability = apply_capability_for("unknown", offer.url)
    else:
        capability = apply_capability_for(response_type, offer.url)

    partner_url = ""
    partner_text = ""
    method = "none"

    # Toujours tenter la page réelle (ATS) derrière LinkedIn / HW / Indeed / Adzuna
    deep = _page_fetch_deep(offer.url)
    # Vérif Workday Airbus HORS lock Chrome (évite deadlock)
    try:
        import page_fetch as _pf

        listing_for_ref = deep.get("listing_text") or offer.description or ""
        ref = ""
        if hasattr(_pf, "extract_job_ref"):
            ref = _pf.extract_job_ref(listing_for_ref)
        if not ref:
            m = re.search(r"\b(JR\d{5,})\b", listing_for_ref, re.I)
            ref = m.group(1).upper() if m else ""
        company_l = f"{offer.company or ''} {listing_for_ref[:500]}".lower()
        if ref and "airbus" in company_l and hasattr(_pf, "check_airbus_workday_ref"):
            chk = _pf.check_airbus_workday_ref(ref)
            if not chk.get("alive"):
                deep = dict(deep)
                deep["dead"] = True
                deep["method"] = "ats_dead"
                deep["ats_url"] = chk.get("url") or deep.get("ats_url") or ""
                deep["final_url"] = deep["ats_url"]
                deep["ats_text"] = ""
                LOG.info("airbus ref %s dead: %s", ref, chk.get("detail"))
    except Exception as exc:
        LOG.info("airbus ref check skip: %s", exc)

    if deep.get("dead") or deep.get("method") == "ats_dead":
        partner_url = deep.get("final_url") or deep.get("ats_url") or partner_url
        method = "ats_dead"
        partner_text = ""
        # Marquer l'offre : lien recruteur cassé / offre absente de l'ATS
        note_dead = (
            f"\n[partner_dead] lien recruteur mort ou offre absente ATS "
            f"({deep.get('method')}) url={partner_url}"
        )
        with store._db() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                UPDATE offers
                   SET apply_capability = ?,
                       partner_url = ?,
                       partner_checked_at = ?,
                       status = CASE WHEN status IN ('applied','interview','replied') THEN status ELSE 'ignored' END,
                       notes = COALESCE(notes, '') || ?,
                       score = CASE WHEN score > 20 THEN 20 ELSE score END
                 WHERE id = ?
                """,
                (
                    "dead_partner",
                    partner_url,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    note_dead,
                    offer.id,
                ),
            )
        return {
            "id": offer.id,
            "company": offer.company,
            "title": offer.title,
            "skipped": False,
            "response_type": "dead_partner",
            "apply_capability": "dead_partner",
            "partner_url": partner_url,
            "method": "ats_dead",
            "score": 20,
            "rejected": True,
            "reject_reason": "partner_link_dead",
            "status": "ignored",
            "auto_submit": False,
            "manual_required": False,
        }
    if deep.get("ats_text") and _partner_text_ok(deep["ats_text"]):
        partner_url = _sanitize_partner_url(
            deep.get("final_url") or deep.get("ats_url") or partner_url
        )
        if not partner_url:
            partner_url = _sanitize_partner_url(deep.get("ats_url") or "")
        if not partner_url:
            partner_text = ""
            method = "ats_rejected_bad_host"
        else:
            partner_text = deep["ats_text"]
            method = f"ats:{deep.get('method')}"
    elif deep.get("listing_text") and _partner_text_ok(deep["listing_text"]):
        # enrichissement listing si plus riche / plus propre que le teaser stocké
        listing = deep["listing_text"]
        if len(listing) > max(400, len(offer.description or "")):
            partner_text = listing
            method = "listing_deep"

    if html:
        jobposting = extract_jobposting_jsonld(html)
        if jobposting:
            if not partner_text and _partner_text_ok(jobposting.get("description") or ""):
                partner_text = jobposting["description"]
                method = "jsonld_jobposting"
            if jobposting.get("email") and jobposting["email"] not in (offer.notes or ""):
                offer.notes = (offer.notes or "") + f"\n[jsonld_contact] {jobposting['email']}"

    if html and not partner_text:
        externals = _extract_external_urls(html)
        if externals:
            _rate_limit_host(externals[0])
            fetched_ext = _page_fetch(externals[0])
            if fetched_ext:
                partner_url = externals[0]
                partner_text = fetched_ext
                method = "html_external_link"

    if len(partner_text) < 300 and response_type in ("partner", "ats", "unknown", "direct_source"):
        apec_url, apec_text = _fetch_apec_match(offer)
        if len(apec_text) > len(partner_text):
            partner_url = apec_url or partner_url
            partner_text = apec_text
            method = "apec_match"

    if len(partner_text) < 300 and partner_url:
        _rate_limit_host(partner_url)
        partner_text = _page_fetch(partner_url) or partner_text
        method = method if method != "none" else "page_fetch"

    if partner_text:
        _merge_partner_text(offer, partner_text)
        if response_type in ("partner", "ats"):
            offer.apply_mode = "partner_manual"

    if offer.latitude is None and offer.city:
        try:
            geo.resolve(offer)
        except Exception:
            pass

    result = scoring.evaluate(offer)
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    meta = {
        "at": stamp,
        "response_type": response_type,
        "apply_capability": capability,
        "partner_url": partner_url,
        "method": method,
        "partner_chars": len(partner_text or ""),
        "score": result.value,
        "rejected": result.rejected,
        "reject_reason": result.reject_reason,
        "reasons": result.reasons[:12],
    }
    note = f"\n[partner_deep] {json.dumps(meta, ensure_ascii=False)}"

    previous = store.get(offer.id)
    prev_status = previous["status"] if previous else "new"
    store.save_offer(offer, result)

    new_status = prev_status
    if result.rejected and prev_status in ("new", "shortlist", "prepared"):
        new_status = "ignored"
        store.set_status(offer.id, "ignored")
        with store._db() as conn:  # type: ignore[attr-defined]
            conn.execute("DELETE FROM plan WHERE offer_id=?", (offer.id,))
            conn.execute("DELETE FROM kits WHERE offer_id=?", (offer.id,))
    elif scoring.is_eligible_for_plan(result, capability, campaign=scoring.campaign_of(offer)) and prev_status == "new":
        new_status = "shortlist"
        store.set_status(offer.id, "shortlist")


    # Sonde ATS JSON si on a une URL partenaire
    if partner_url and method not in ("ats_dead",):
        try:
            alive = ats_alive.check(partner_url)
            if alive.get("alive") is False:
                method = "ats_dead"
                note_dead = (
                    f"\n[partner_dead] ATS JSON mort ({alive.get('reason')}) "
                    f"probe={alive.get('probe_url')}"
                )
                with store._db() as conn:  # type: ignore[attr-defined]
                    conn.execute(
                        """
                        UPDATE offers
                           SET apply_capability = ?,
                               partner_url = ?,
                               partner_checked_at = ?,
                               status = CASE WHEN status IN ('applied','interview','replied') THEN status ELSE 'ignored' END,
                               notes = COALESCE(notes, '') || ?,
                               score = CASE WHEN score > 20 THEN 20 ELSE score END
                         WHERE id = ?
                        """,
                        (
                            "dead_partner",
                            partner_url,
                            datetime.now().astimezone().isoformat(timespec="seconds"),
                            note_dead,
                            offer.id,
                        ),
                    )
                return {
                    "id": offer.id,
                    "company": offer.company,
                    "title": offer.title,
                    "skipped": False,
                    "response_type": "dead_partner",
                    "apply_capability": "dead_partner",
                    "partner_url": partner_url,
                    "method": "ats_dead",
                    "score": 20,
                    "rejected": True,
                    "reject_reason": "partner_link_dead",
                    "status": "ignored",
                    "auto_submit": False,
                    "manual_required": False,
                }
        except Exception as exc:
            LOG.info("ats_alive skip: %s", exc)


    with store._db() as conn:  # type: ignore[attr-defined]
        conn.execute(
            """
            UPDATE offers
               SET partner_url = ?,
                   apply_capability = ?,
                   partner_checked_at = ?,
                   notes = COALESCE(notes, '') || ?
             WHERE id = ?
            """,
            (partner_url, capability, stamp, note, offer.id),
        )

    report = {
        "id": offer.id,
        "company": offer.company,
        "title": offer.title,
        "skipped": False,
        "response_type": response_type,
        "apply_capability": capability,
        "partner_url": partner_url,
        "method": method,
        "score": result.value,
        "rejected": result.rejected,
        "reject_reason": result.reject_reason,
        "status": new_status,
        "auto_submit": capability == "auto_hellowork" and not result.rejected,
        "manual_required": capability.startswith("manual") and not result.rejected,
    }
    LOG.info(
        "deep %s %s score=%s cap=%s method=%s rej=%s",
        offer.id,
        offer.company,
        result.value,
        capability,
        method,
        result.rejected,
    )
    return report


def enrich_pending(limit: int = MAX_PER_RUN, force: bool = False) -> list[dict]:
    ensure_columns()
    bounded_limit = max(0, int(limit))
    if bounded_limit == 0:
        return []
    where = "status IN ('new', 'shortlist', 'prepared')"
    if not force:
        where += " AND (apply_capability IS NULL OR apply_capability = '')"
    query = f"""
        SELECT *
          FROM offers
         WHERE {where}
         ORDER BY
           CASE
             WHEN LOWER(COALESCE(url, '')) LIKE '%hellowork.com%'
                  AND (apply_capability IS NULL OR apply_capability = '') THEN 0
             WHEN LOWER(COALESCE(url, '')) LIKE '%hellowork.com%' THEN 1
             ELSE 2
           END,
           COALESCE(score, 0) DESC,
           first_seen DESC,
           id DESC
         LIMIT ?
    """
    with store._db() as conn:  # type: ignore[attr-defined]
        targets = list(conn.execute(query, (bounded_limit,)))
    reports: list[dict] = []
    for row in targets:
        offer = offers.from_row(row)
        _rate_limit_host(offer.url)
        try:
            reports.append(enrich_offer(offer, force=force))
        except Exception as exc:
            LOG.exception("enrich %s: %s", row["id"], exc)
            reports.append({"id": row["id"], "error": str(exc)})
    return reports


TARGET_KEEP_MANUAL = (
    "cyber", "soc", "siem", "securite", "reseau", "infrastructure", "systeme",
    "sysadmin", "administrateur", "pentest", "edr", "grc", "rssi", "incident",
    "cloud", "devops", "devsecops", "sre", "aws", "azure", "kubernetes", "docker",
    "terraform", "ansible", "linux", "windows server", "active directory",
    "support", "helpdesk", "service desk", "itsm", "gestion de parc", "mdm",
    "exploitation", "mco", "virtualisation", "vmware", "proxmox",
    "qualite", "recette", "test", "validation", "base de donnees", "sql",
)

def manual_queue(limit: int = 30) -> list[dict]:
    ensure_columns()
    out: list[dict] = []
    for row in store.list_offers(min_score=65, limit=300):
        if row["status"] not in ("shortlist", "prepared", "new"):
            continue
        cap = _capability_from_row(row)
        if str(cap).startswith("manual"):
            offer_obj = offers.from_row(row)
            if scoring.campaign_of(offer_obj) != "job":
                blob = fold(f"{row['title']} {row['description'] or ''}")
                if not any(k in blob for k in TARGET_KEEP_MANUAL):
                    continue
            item = dict(row)
            item["apply_capability"] = cap
            out.append(item)
        if len(out) >= limit:
            break
    return out


def auto_queue(limit: int = 30) -> list[dict]:
    ensure_columns()
    out: list[dict] = []
    for row in store.list_offers(min_score=profile.AUTO_HELLOWORK_MIN_SCORE, limit=300):
        if row["status"] not in ("shortlist", "prepared", "new"):
            continue
        if _capability_from_row(row) != "auto_hellowork":
            continue
        if int(row["score"] or 0) >= profile.MIN_SCORE:
            out.append(dict(row))
        else:
            offer_obj = offers.from_row(row)
            if scoring.is_eligible_for_plan(
                scoring.evaluate(offer_obj),
                "auto_hellowork",
                campaign=scoring.campaign_of(offer_obj),
            ):
                out.append(dict(row))
        if len(out) >= limit:
            break
    return out

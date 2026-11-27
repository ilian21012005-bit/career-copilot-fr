"""Sonde les ATS SPA via leurs API JSON (pas seulement HTTP 200 page).

Inspiré de job-search-automations / jobseek :
- Workday CXS : 200+jobPostingInfo = vivant ; 404 ou 403/S22 = mort
- Greenhouse boards API
- Ashby job board listing
- Lever postings API
- SmartRecruiters public postings API
- Recruitee public offers API
- Teamtailor `/jobs.rss` + fallback soft-404
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse
import public_network

LOG = logging.getLogger("hellowork.ats_alive")
UA = "Mozilla/5.0 (compatible; JobEtudiantBot/1.0; +local)"
TTL_HOURS = 24
MAX_PER_HOST = 20
HOST_DELAY_SEC = 0.25


def check(url: str, timeout: float = 12.0) -> dict[str, Any]:
    """Retourne {alive: bool|None, reason, ats, probe_url}.

    alive=None → indéterminé (ne pas ignorer l'offre).
    """
    url = (url or "").strip()
    try:
        _, host, _, _ = public_network.target(url)
    except ValueError:
        return {"alive": None, "reason": "bad_url", "ats": "", "probe_url": ""}

    if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
        return _workday(url, timeout)
    if "greenhouse.io" in host or "boards.greenhouse.io" in host:
        return _greenhouse(url, timeout)
    if "ashbyhq.com" in host:
        return _ashby(url, timeout)
    if "lever.co" in host:
        return _lever(url, timeout)
    if "smartrecruiters.com" in host:
        return _smartrecruiters(url, timeout)
    if "recruitee.com" in host:
        return _recruitee(url, timeout)
    if "teamtailor.com" in host:
        return _teamtailor(url, timeout)
    if "icims.com" in host:
        return _http_soft(url, timeout, ats="icims")
    return _http_soft(url, timeout, ats="generic")


def _get(url: str, timeout: float, accept: str = "application/json") -> tuple[int, bytes]:
    try:
        return public_network.fetch(url, headers={"User-Agent": UA, "Accept": accept}, timeout=timeout)
    except Exception as exc:
        LOG.info("probe fail: %s", type(exc).__name__)
        return -1, b""


def _workday(url: str, timeout: float) -> dict[str, Any]:
    """Convertit une URL publique Workday en endpoint CXS detail."""
    # https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/Paris/Title_JR123
    # -> https://ag.wd3.myworkdayjobs.com/wday/cxs/ag/Airbus/job/...
    m = re.match(
        r"https://([\w-]+)\.(wd[\w-]*)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)/job/(.+?)(?:\?|$)",
        url,
    )
    if not m:
        # search URL ?q=JR...
        mq = re.search(r"[?&]q=(JR\d+)", url, re.I)
        if mq:
            return {
                "alive": None,
                "reason": "workday_search_only",
                "ats": "workday",
                "probe_url": url,
                "ref": mq.group(1).upper(),
            }
        return {"alive": None, "reason": "workday_unparsed", "ats": "workday", "probe_url": url}

    tenant, instance, site, path = m.groups()
    path = path.rstrip("/")
    probe = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}"
    status, body = _get(probe, timeout)
    if status == 404:
        return {"alive": False, "reason": "workday_404", "ats": "workday", "probe_url": probe}
    if status == 403:
        try:
            data = json.loads(body.decode("utf-8", errors="ignore"))
            if str(data.get("errorCode") or "") == "S22":
                return {"alive": False, "reason": "workday_S22", "ats": "workday", "probe_url": probe}
        except Exception:
            pass
        return {"alive": None, "reason": "workday_403", "ats": "workday", "probe_url": probe}
    if status == 200:
        try:
            data = json.loads(body.decode("utf-8", errors="ignore"))
            if data.get("jobPostingInfo") or data.get("jobPostingId"):
                return {"alive": True, "reason": "workday_ok", "ats": "workday", "probe_url": probe}
        except Exception:
            pass
        return {"alive": None, "reason": "workday_200_no_info", "ats": "workday", "probe_url": probe}
    return {"alive": None, "reason": f"workday_status_{status}", "ats": "workday", "probe_url": probe}


def _greenhouse(url: str, timeout: float) -> dict[str, Any]:
    # boards.greenhouse.io/company/jobs/12345
    m = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
    if not m:
        return {"alive": None, "reason": "greenhouse_unparsed", "ats": "greenhouse", "probe_url": url}
    company, jid = m.groups()
    probe = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs/{jid}"
    status, body = _get(probe, timeout)
    if status == 404:
        return {"alive": False, "reason": "greenhouse_404", "ats": "greenhouse", "probe_url": probe}
    if status == 200:
        try:
            data = json.loads(body)
            if isinstance(data, dict) and str(data.get("id")) == jid:
                return {"alive": True, "reason": "greenhouse_ok", "ats": "greenhouse", "probe_url": probe}
        except (ValueError, TypeError):
            pass
    return {"alive": None, "reason": f"greenhouse_{status}", "ats": "greenhouse", "probe_url": probe}


def _ashby(url: str, timeout: float) -> dict[str, Any]:
    # jobs.ashbyhq.com/org/uuid-or-slug
    m = re.search(r"ashbyhq\.com/([^/?#]+)/([^/?#]+)", url)
    if not m:
        return {"alive": None, "reason": "ashby_unparsed", "ats": "ashby", "probe_url": url}
    org, job = m.groups()
    probe = f"https://api.ashbyhq.com/posting-api/job-board/{org}?listedOnly=true"
    status, body = _get(probe, timeout)
    if status != 200:
        return {"alive": None, "reason": f"ashby_board_{status}", "ats": "ashby", "probe_url": probe}
    try:
        data = json.loads(body.decode("utf-8", errors="ignore"))
    except Exception:
        return {"alive": None, "reason": "ashby_bad_json", "ats": "ashby", "probe_url": probe}
    if not isinstance(data, dict):
        return {"alive": None, "reason": "ashby_bad_json", "ats": "ashby", "probe_url": probe}
    jobs = data.get("jobs")
    if jobs is None and isinstance(data.get("jobBoard"), dict):
        jobs = data["jobBoard"].get("jobPostings")
    if not isinstance(jobs, list):
        return {"alive": None, "reason": "ashby_missing_jobs", "ats": "ashby", "probe_url": probe}
    for j in jobs:
        if not isinstance(j, dict):
            continue
        posted_id = str(j.get("id") or "").lower()
        posted_url = str(j.get("jobUrl") or j.get("jobPostingUrl") or "")
        posted_path_id = urlparse(posted_url).path.rstrip("/").split("/")[-1].lower()
        if job.lower() in (posted_id, posted_path_id):
            if j.get("isListed") is False:
                continue
            return {"alive": True, "reason": "ashby_listed", "ats": "ashby", "probe_url": probe}
    return {"alive": False, "reason": "ashby_not_listed", "ats": "ashby", "probe_url": probe}


def _lever(url: str, timeout: float) -> dict[str, Any]:
    # jobs.lever.co/company/uuid
    m = re.search(r"lever\.co/([^/?#]+)/([a-f0-9-]{10,})", url, re.I)
    if not m:
        return {"alive": None, "reason": "lever_unparsed", "ats": "lever", "probe_url": url}
    company, jid = m.groups()
    probe = f"https://api.lever.co/v0/postings/{company}/{jid}"
    status, body = _get(probe, timeout)
    if status == 404:
        return {"alive": False, "reason": "lever_404", "ats": "lever", "probe_url": probe}
    if status == 200:
        try:
            data = json.loads(body)
            if isinstance(data, dict) and str(data.get("id") or "").lower() == jid.lower():
                return {"alive": True, "reason": "lever_ok", "ats": "lever", "probe_url": probe}
        except (ValueError, TypeError):
            pass
    return {"alive": None, "reason": f"lever_{status}", "ats": "lever", "probe_url": probe}


def _smartrecruiters(url: str, timeout: float) -> dict[str, Any]:
    # jobs.smartrecruiters.com/Company/744000161334061-slug
    m = re.search(r"smartrecruiters\.com/([^/?#]+)/([^/?#]+)", url, re.I)
    if not m:
        return {"alive": None, "reason": "smartrecruiters_unparsed", "ats": "smartrecruiters", "probe_url": url}
    company, raw_pid = m.groups()
    m_id = re.match(r"^(\d+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-|$)", raw_pid, re.I)
    pid = m_id.group(1) if m_id else raw_pid.split("-")[0]
    if not pid:
        return {"alive": None, "reason": "smartrecruiters_unparsed", "ats": "smartrecruiters", "probe_url": url}
    probe = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{pid}"
    status, body = _get(probe, timeout)
    if status == 404:
        return {"alive": False, "reason": "smartrecruiters_404", "ats": "smartrecruiters", "probe_url": probe}
    if status == 200:
        try:
            data = json.loads(body.decode("utf-8", errors="ignore"))
            if isinstance(data, dict):
                if data.get("active") is False:
                    return {"alive": False, "reason": "smartrecruiters_inactive", "ats": "smartrecruiters", "probe_url": probe}
                returned = {str(data.get("id") or "").lower(), str(data.get("uuid") or "").lower()}
                if pid.lower() in returned:
                    return {"alive": True, "reason": "smartrecruiters_ok", "ats": "smartrecruiters", "probe_url": probe}
                return {"alive": False, "reason": "smartrecruiters_mismatch", "ats": "smartrecruiters", "probe_url": probe}
        except (ValueError, TypeError):
            pass
    return {"alive": None, "reason": f"smartrecruiters_{status}", "ats": "smartrecruiters", "probe_url": probe}


def _recruitee(url: str, timeout: float) -> dict[str, Any]:
    # company.recruitee.com/o/offer-slug or /offers/offer-slug
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    m = re.match(r"^/(?:o|offers)/([^/?#]+)", parsed.path or "", re.I)
    if not host or not m:
        return {"alive": None, "reason": "recruitee_unparsed", "ats": "recruitee", "probe_url": url}
    slug = m.group(1)
    probe = f"https://{host}/api/offers/{slug}"
    status, body = _get(probe, timeout)
    if status in (404, 410):
        return {"alive": False, "reason": f"recruitee_{status}", "ats": "recruitee", "probe_url": probe}
    if status == 200:
        try:
            data = json.loads(body.decode("utf-8", errors="ignore"))
            offer = data.get("offer") if isinstance(data, dict) and isinstance(data.get("offer"), dict) else data
            if isinstance(offer, dict):
                if str(offer.get("status") or "").lower() in {"closed", "archived", "draft"}:
                    return {"alive": False, "reason": "recruitee_closed", "ats": "recruitee", "probe_url": probe}
                returned_slug = str(offer.get("slug") or "").lower()
                if not returned_slug or returned_slug == slug.lower():
                    return {"alive": True, "reason": "recruitee_ok", "ats": "recruitee", "probe_url": probe}
                return {"alive": False, "reason": "recruitee_mismatch", "ats": "recruitee", "probe_url": probe}
        except (ValueError, TypeError):
            pass
    return {"alive": None, "reason": f"recruitee_{status}", "ats": "recruitee", "probe_url": probe}


def _teamtailor(url: str, timeout: float) -> dict[str, Any]:
    # company.teamtailor.com/jobs/12345-title
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    m = re.search(r"/jobs/(\d+)(?:-|$)", parsed.path or "", re.I)
    if not host or not m:
        return _http_soft(url, timeout, ats="teamtailor")
    job_id = m.group(1)
    probe = f"https://{host}/jobs.rss"
    status, body = _get(probe, timeout, accept="application/rss+xml, application/xml, text/xml")
    if status == 200 and body and b"<!ENTITY" not in body[:4096].upper():
        xml_text = body.decode("utf-8", errors="ignore")
        if f"/jobs/{job_id}" in xml_text or f">{job_id}<" in xml_text:
            return {"alive": True, "reason": "teamtailor_rss_ok", "ats": "teamtailor", "probe_url": probe}
    return _http_soft(url, timeout, ats="teamtailor")


def _http_soft(url: str, timeout: float, ats: str) -> dict[str, Any]:
    status, body = _get(url, timeout, accept="text/html,application/json")
    if status in (404, 410):
        return {"alive": False, "reason": f"{ats}_{status}", "ats": ats, "probe_url": url}
    if status == -1:
        return {"alive": None, "reason": f"{ats}_network", "ats": ats, "probe_url": url}
    text = body.decode("utf-8", errors="ignore").lower()[:200_000]
    dead_signals = (
        "job is no longer available",
        "no longer accepting applications",
        "page not found",
        "n'existe pas",
        "n’existe pas",
        "offre n'est plus disponible",
        "offre n’est plus disponible",
        "cette offre n'est plus disponible",
        "cette offre n’est plus disponible",
        "cette offre est expir",
        "offre expirée",
        "offre expiree",
        "offre pourvue",
        "offre clôturée",
        "offre cloturee",
        "annonce expirée",
        "annonce expiree",
        "n'est plus en ligne",
        "n’est plus en ligne",
        "this job has been filled",
        "offer has expired",
        "job has expired",
    )
    if status == 200 and any(s in text for s in dead_signals):
        return {"alive": False, "reason": f"{ats}_soft404", "ats": ats, "probe_url": url}
    if status == 200:
        return {"alive": True, "reason": f"{ats}_200", "ats": ats, "probe_url": url}
    return {"alive": None, "reason": f"{ats}_{status}", "ats": ats, "probe_url": url}


def _probe_host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if "greenhouse.io" in host:
        return "boards-api.greenhouse.io"
    if "ashbyhq.com" in host:
        return "api.ashbyhq.com"
    if "lever.co" in host:
        return "api.lever.co"
    if "smartrecruiters.com" in host:
        return "api.smartrecruiters.com"
    return host


def _is_recently_checked(
    checked_at: str | None,
    *,
    ttl_hours: float = TTL_HOURS,
    now: datetime | None = None,
) -> bool:
    if not checked_at or ttl_hours <= 0:
        return False
    try:
        dt = datetime.fromisoformat(str(checked_at).strip())
    except ValueError:
        return False
    current = now or datetime.now().astimezone()
    if dt.tzinfo is None and current.tzinfo is not None:
        dt = dt.replace(tzinfo=current.tzinfo)
    elif dt.tzinfo is not None and current.tzinfo is None:
        current = current.replace(tzinfo=dt.tzinfo)
    return (current - dt).total_seconds() < ttl_hours * 3600


def check_batch(
    items: Iterable[Mapping[str, Any]],
    *,
    force: bool = False,
    ttl_hours: float = TTL_HOURS,
    timeout: float = 8.0,
    max_workers: int = 12,
    max_per_host: int = MAX_PER_HOST,
    host_delay: float = HOST_DELAY_SEC,
    now: datetime | None = None,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> list[dict[str, Any]]:
    """Sonde un lot d'offres en respectant `partner_checked_at` (TTL) et le débit par hôte."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    sleep_fn = sleep or time.sleep
    mono_fn = monotonic or time.monotonic
    delay_s = max(0.0, float(host_delay))
    host_cap = int(max_per_host)

    results: list[dict[str, Any]] = []
    queued: list[tuple[str, str, str, dict[str, Any]]] = []
    host_counts: dict[str, int] = defaultdict(int)
    host_locks: dict[str, threading.Lock] = {}
    host_last_at: dict[str, float] = {}

    for raw_item in items:
        row = dict(raw_item)
        url = str(row.get("probe_url") or row.get("apply_url") or row.get("partner_url") or row.get("url") or "").strip()
        ident = str(row.get("id") or url)
        if not url:
            continue
        if not force and _is_recently_checked(row.get("partner_checked_at"), ttl_hours=ttl_hours, now=now):
            results.append({
                "id": ident,
                "url": url,
                "skipped": True,
                "skip_reason": "ttl_fresh",
                "alive": None,
                "item": row,
            })
            continue
        host = _probe_host(url) or "_invalid"
        if host_cap > 0 and host_counts[host] >= host_cap:
            results.append({
                "id": ident,
                "url": url,
                "skipped": True,
                "skip_reason": "host_limit",
                "alive": None,
                "item": row,
            })
            continue
        host_counts[host] += 1
        host_locks.setdefault(host, threading.Lock())
        queued.append((ident, url, host, row))

    def _probe_one(ident: str, url: str, host: str, row: dict[str, Any]) -> dict[str, Any]:
        with host_locks[host]:
            if delay_s > 0:
                last = host_last_at.get(host)
                if last is not None:
                    wait = delay_s - (mono_fn() - last)
                    if wait > 0:
                        sleep_fn(wait)
            res = check(url, timeout=timeout)
            host_last_at[host] = mono_fn()
        return {"id": ident, "url": url, "skipped": False, "skip_reason": "", "item": row, **res}

    if queued:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 16))) as pool:
            futs = [pool.submit(_probe_one, ident, url, host, row) for ident, url, host, row in queued]
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception:
                    continue
    return results


def prune_dead_offers(
    limit_hw: int = 200,
    limit_suivi: int = 500,
    timeout: float = 8.0,
    max_workers: int = 12,
    force: bool = False,
    ttl_hours: float = TTL_HOURS,
    max_per_host: int = MAX_PER_HOST,
    host_delay: float = HOST_DELAY_SEC,
) -> dict[str, int]:
    """Sonde les offres actives HelloWork + Suivi et ignore uniquement celles confirmées mortes."""
    from . import store
    import suivi

    store.init()
    skipped_ttl = 0
    hw_items: list[dict[str, Any]] = []
    for raw in store.list_offers(min_score=0, limit=max(limit_hw, 5000)):
        row = dict(raw)
        if row.get("status") not in ("new", "shortlist", "prepared"):
            continue
        probe_url = (row.get("apply_url") or row.get("partner_url") or row.get("url") or "").strip()
        if not probe_url:
            continue
        if not force and _is_recently_checked(row.get("partner_checked_at"), ttl_hours=ttl_hours):
            skipped_ttl += 1
            continue
        hw_items.append({
            "id": str(row["id"]),
            "probe_url": probe_url,
            "partner_checked_at": row.get("partner_checked_at"),
            "_kind": "hw",
        })
        if len(hw_items) >= limit_hw:
            break

    suivi_items: list[dict[str, Any]] = []
    for row in suivi.list_rows():
        if row.get("status") in ("Ignorée", "Postulé", "Transmise", "Entretien", "Répondu", "Refus"):
            continue
        url = str(row.get("url") or "").strip()
        if url:
            suivi_items.append({
                "id": url,
                "probe_url": url,
                "partner_checked_at": row.get("partner_checked_at"),
                "_kind": "suivi",
            })
        if len(suivi_items) >= limit_suivi:
            break

    batch_results = check_batch(
        hw_items + suivi_items,
        force=force,
        ttl_hours=ttl_hours,
        timeout=timeout,
        max_workers=max_workers,
        max_per_host=max_per_host,
        host_delay=host_delay,
    )

    hw_ignored = 0
    dead_suivi_urls: set[str] = set()
    checked_hw_ids: list[str] = []
    checked = 0
    skipped_host_limit = 0
    for res in batch_results:
        if res.get("skipped"):
            if res.get("skip_reason") == "host_limit":
                skipped_host_limit += 1
            elif res.get("skip_reason") == "ttl_fresh":
                skipped_ttl += 1
            continue
        checked += 1
        item = res.get("item") or {}
        if item.get("_kind") == "hw":
            if res.get("alive") is not None:
                checked_hw_ids.append(str(res["id"]))
            if res.get("alive") is False:
                reason = str(res.get("reason") or "dead")
                if store.set_status(str(res["id"]), "ignored", note=f"Lien mort auto ({reason})",
                                    expected_statuses=("new", "shortlist", "prepared")):
                    hw_ignored += 1
        elif res.get("alive") is False:
            dead_suivi_urls.add(str(res["url"]))

    if checked_hw_ids:
        store.mark_partner_checked(checked_hw_ids)

    suivi_ignored = suivi.mark_ignored_many(dead_suivi_urls) if dead_suivi_urls else 0
    return {
        "checked": checked,
        "hw_ignored": hw_ignored,
        "suivi_ignored": suivi_ignored,
        "total_ignored": hw_ignored + suivi_ignored,
        "skipped_ttl": skipped_ttl,
        "skipped_host_limit": skipped_host_limit,
    }

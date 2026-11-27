"""Lit le texte d'une annonce, y compris la page de l'employeur derrière Adzuna."""

from __future__ import annotations

import base64
import atexit
import json
from pathlib import Path
import os
import errno
import signal
import socket
import struct
import subprocess
import threading
import tempfile
import time
import re
import urllib.parse
import urllib.request

import pdfs
import public_network

PORT = 9334
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_LOCK = threading.Lock()
_BROWSER = None
_BROWSER_PROFILE = None
_ATEXIT_REGISTERED = False
_LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _is_safe_http_url(url: str) -> bool:
    try:
        public_network.target(url)
        return True
    except ValueError:
        return False


def read_via_jina(url: str, *, fetcher=None, timeout: float = 15.0) -> str:
    """Extraction Markdown lecture seule via r.jina.ai pour pages JS publiques.

    Ne transmet jamais de CV ni d'URL privée/locale (validée par `public_network.target`).
    Le texte renvoyé reste traité comme une donnée externe non fiable.
    """
    raw_url = (url or "").strip()
    if not raw_url:
        return ""
    try:
        scheme, host, port, _ = public_network.target(raw_url)
    except ValueError:
        return ""
    if scheme != "https" or not host:
        return ""
    jina_url = f"https://r.jina.ai/{raw_url}"
    try:
        fetch_fn = fetcher or (
            lambda target_url: public_network.fetch(
                target_url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
                timeout=timeout,
            )
        )
        status, body = fetch_fn(jina_url)
    except Exception:
        return ""
    if status != 200 or not body:
        return ""
    text = body.decode("utf-8", errors="replace")
    cleaned = _strip_junk_chrome_text(text)
    if page_looks_dead(cleaned, "", raw_url):
        return ""
    return cleaned[:12000]


def read_offer(url: str) -> str:
    if not _is_safe_http_url(url or ""):
        return ""
    text = ""
    with _LOCK:
        try:
            _ensure()
            ws_url, tab_id = _open_tab()
            try:
                _navigate(ws_url, url)
                text = _wait_text(ws_url)
                land = _eval(ws_url, "(document.querySelector('a[href*=\"/land/ad/\"]') || {}).href || ''")
                if _is_safe_http_url(land):
                    _navigate(ws_url, land)
                    landed = _wait_text(ws_url, minimum=450)
                    if _score(landed) > _score(text):
                        text = landed
            finally:
                _close_tab(tab_id)
        except Exception:
            text = ""
    if (
        len(text.strip()) < 180
        and os.getenv("JINA_READER_FALLBACK", "").strip().lower() in {"1", "true", "yes"}
    ):
        jina_text = read_via_jina(url)
        if _score(jina_text) > _score(text):
            return jina_text
    return text



def _guess_ats_from_listing(listing: str, page_url: str = "") -> str:
    """Devine une URL ATS à partir du texte listing (Réf, liens bruts)."""
    if not listing:
        return ""
    # Liens ATS déjà présents dans le texte
    for m in re.finditer(r"https?://[^\s<>\"']+", listing):
        u = m.group(0).rstrip(").,;]")
        low = u.lower()
        if any(b in low for b in ("hellowork", "linkedin.com", "indeed.", "adzuna", "apps.apple", "facebook", "google.")):
            continue
        if any(p in low for p in (
            "smartrecruiters", "myworkdayjobs", "greenhouse", "lever.co", "icims",
            "teamtailor", "welcometothejungle", "talent-soft", "talentsoft", "ashbyhq",
            "workable", "successfactors", "phenompeople",
        )):
            if _is_safe_http_url(u):
                return u
    # Framatome talent-soft depuis Réf 2026-27990
    ref = ""
    m = re.search(r"R[ée]f\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9_./-]{2,})", listing, re.I)
    if m:
        ref = m.group(1).strip()
    company_hint = listing.lower()
    if ref and "framatome" in company_hint:
        # 2026-27990 -> idOffre=27990
        num = ref.split("-")[-1] if "-" in ref else ref
        if num.isdigit():
            u = (
                "https://framatome-career.talent-soft.com/Pages/Offre/detailoffre.aspx"
                f"?idOffre={num}&offerReference={ref}"
            )
            if _is_safe_http_url(u):
                return u
    return ""


def _strip_junk_chrome_text(text: str) -> str:
    t = text or ""
    # Couper bannières cookies LinkedIn en tête
    markers = (
        "LinkedIn respects your privacy",
        "Accepter les cookies",
        "Accept cookies",
        "Let's confirm you are human",
    )
    low = t
    for mk in markers:
        idx = low.find(mk)
        if 0 <= idx < 800:
            # chercher début utile après
            for needle in ("À propos", "About the job", "Description", "Missions", "Postuler", "Stage"):
                j = low.find(needle, idx + len(mk))
                if j > 0:
                    t = t[j:]
                    break
    return t.strip()




def extract_job_ref(listing: str) -> str:
    m = re.search(r"\b(JR\d{5,})\b", listing or "", re.I)
    return (m.group(1).upper() if m else "")


def page_looks_dead(text: str, title: str = "", url: str = "") -> bool:
    """Heuristique 404 / offre retirée / page introuvable."""
    blob = f"{title}\n{text}\n{url}".lower()
    if not (text or "").strip() and not title:
        return True
    signals = (
        "page que vous recherchez n'existe pas",
        "page que vous recherchez n’existe pas",
        "page introuvable",
        "n'existe pas",
        "n’existe pas",
        "404 – page not found",
        "404 - page not found",
        "page not found",
        "job is no longer available",
        "no longer accepting applications",
        "this job is closed",
        "cette offre n'est plus disponible",
        "cette offre n’est plus disponible",
        "offre expirée",
        "0 jobs found",
        "there are no job openings",
        "sorry, the page you are looking for flew away",
    )
    return any(s in blob for s in signals)


def check_airbus_workday_ref(ref: str) -> dict:
    """Vérifie si une réf JR###### existe encore sur Workday Airbus.

    Retourne {alive: bool, url: str, detail: str}.
    """
    ref = (ref or "").strip().upper()
    empty = {"alive": False, "url": "", "detail": "no_ref"}
    if not re.fullmatch(r"JR\d{5,}", ref):
        return empty
    search = f"https://ag.wd3.myworkdayjobs.com/en-US/Airbus?q={ref}"
    with _LOCK:
        try:
            _ensure()
            ws_url, tab_id = _open_tab()
            try:
                _navigate(ws_url, search)
                time.sleep(2.0)
                _eval(
                    ws_url,
                    """(() => {
                      for (const b of document.querySelectorAll('button, a')) {
                        const t = (b.innerText||'').toLowerCase();
                        if (t.includes('accept') || t.includes('agree') || t.includes('accepter')) {
                          try { b.click(); } catch (e) {}
                        }
                      }
                      return true;
                    })()""",
                )
                time.sleep(2.2)
                text = _wait_text(ws_url, minimum=80)
                low = (text or "").lower()
                if "0 jobs found" in low or "there are no job openings" in low:
                    return {"alive": False, "url": search, "detail": "workday_zero_jobs"}
                if ref.lower() in low and "job found" in low:
                    return {"alive": True, "url": search, "detail": "workday_hit"}
                # URL directe
                direct = f"https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/{ref}"
                _navigate(ws_url, direct)
                time.sleep(1.8)
                text2 = _wait_text(ws_url, minimum=80)
                if page_looks_dead(text2, _eval(ws_url, "document.title") or "", direct):
                    return {"alive": False, "url": direct, "detail": "workday_direct_dead"}
                if len(text2 or "") > 800 and ref.lower() in (text2 or "").lower():
                    return {"alive": True, "url": direct, "detail": "workday_direct_alive"}
                return {"alive": False, "url": search, "detail": "workday_unclear_treat_dead"}
            finally:
                _close_tab(tab_id)
        except Exception as exc:
            return {"alive": False, "url": search, "detail": f"error:{exc}"}



def read_offer_deep(url: str) -> dict:
    """Lit une annonce agrégateur puis suit le lien ATS / site carrière si présent.

    Retourne {listing_text, ats_url, ats_text, final_url, method}.
    Ne contourne pas de CAPTCHA : si la page ATS est bloquée, ats_text reste court.
    """
    empty = {"listing_text": "", "ats_url": "", "ats_text": "", "final_url": "", "method": "none", "dead": False}
    if not _is_safe_http_url(url or ""):
        return empty
    with _LOCK:
        try:
            _ensure()
            ws_url, tab_id = _open_tab()
            try:
                _navigate(ws_url, url)
                listing = _wait_text(ws_url, minimum=220)
                # expand teaser LinkedIn / Indeed
                _eval(
                    ws_url,
                    """(() => {
                      const labels = ['voir plus', 'see more', 'afficher plus', 'show more', 'lire la suite'];
                      for (const el of document.querySelectorAll('button, a')) {
                        const t = (el.innerText || '').trim().toLowerCase();
                        if (labels.some(l => t === l || t.includes(l))) { try { el.click(); } catch (e) {} }
                      }
                      return true;
                    })()"""
                )
                time.sleep(0.6)
                expanded_listing = _wait_text(ws_url, minimum=220)
                if _score(expanded_listing) > _score(listing):
                    listing = expanded_listing  # voir plus linkedin expand
                # Adzuna land redirect
                land = _eval(ws_url, "(document.querySelector('a[href*=\"/land/ad/\"]') || {}).href || ''")
                if _is_safe_http_url(land):
                    _navigate(ws_url, land)
                    landed = _wait_text(ws_url, minimum=450)
                    if _score(landed) > _score(listing):
                        listing = landed
                        url = land

                ats_url = _pick_ats_url(ws_url, url)
                if not ats_url:
                    ats_url = _guess_ats_from_listing(listing, url)
                listing = _strip_junk_chrome_text(listing)
                ats_text = ""
                method = "listing_only"
                final_url = url
                if ats_url and _is_safe_http_url(ats_url) and _host(ats_url) != _host(url):
                    _navigate(ws_url, ats_url)
                    time.sleep(1.2)
                    # wait for SPA ATS
                    ats_text = _wait_text(ws_url, minimum=350)
                    # try expand "voir plus" / show more
                    _eval(
                        ws_url,
                        """(() => {
                          const labels = ['voir plus', 'see more', 'afficher plus', 'show more', 'lire la suite'];
                          for (const el of document.querySelectorAll('button, a')) {
                            const t = (el.innerText || '').trim().toLowerCase();
                            if (labels.some(l => t.includes(l))) { try { el.click(); } catch (e) {} }
                          }
                          return true;
                        })()"""
                    )
                    time.sleep(0.8)
                    expanded = _wait_text(ws_url, minimum=350)
                    if _score(expanded) >= _score(ats_text):
                        ats_text = expanded
                    final_url = _eval(ws_url, "location.href") or ats_url
                    method = "ats_followed"
                ats_text = _strip_junk_chrome_text(ats_text)
                dead = False
                if method == "ats_followed" and page_looks_dead(ats_text, "", final_url or ats_url):
                    dead = True
                    method = "ats_dead"
                    # garder l'URL pour diagnostic mais pas le faux contenu
                    ats_text = ""
                return {
                    "listing_text": listing or "",
                    "ats_url": ats_url or "",
                    "ats_text": ats_text or "",
                    "final_url": final_url or "",
                    "method": method,
                    "dead": dead,
                }
            finally:
                _close_tab(tab_id)
        except Exception:
            return empty


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _pick_ats_url(ws_url: str, current_url: str) -> str:
    """Choisit le meilleur lien postuler / ATS hors agrégateur.

    Refuse pubs / App Store / homepages génériques sans signal job.
    """
    js = r"""
(() => {
  const blockers = [
    'linkedin.com','indeed.com','hellowork.com','adzuna.','jooble.','glassdoor.',
    'google.','facebook.','twitter.','youtube.','bing.com','apps.apple.com',
    'play.google.com','apple.com/fr/iphone','instagram.','tiktok.','whatsapp.',
    'maps.google','goo.gl','bit.ly'
  ];
  const hardAts = [
    'smartrecruiters','myworkdayjobs','workdayjobs','greenhouse.io','boards.greenhouse',
    'lever.co','icims.com','jobvite','taleo.net','successfactors','teamtailor.com',
    'welcometothejungle.com','ashbyhq.com','jobs.lever','oraclecloud.com',
    'softgarden.io','breezy.hr','recruitee.com','personio.de','workable.com',
    'talent-soft.com','talentsoft.com','phenompeople.com','jobteaser.com',
    'phenom.com','jobappnetwork','apply.workable'
  ];
  const softCareer = ['careers.','jobs.','recrutement.','talent.','carrieres.'];
  const cta = ['postuler','apply now','apply','candidater','candidature','voir l\'offre','company website','site de l\'entreprise','postuler sur le site'];
  const urls = [];
  const push = (href, score, label) => {
    try {
      if (!href || !href.startsWith('http')) return;
      const u = new URL(href);
      const host = u.hostname.toLowerCase();
      const full = (href || '').toLowerCase();
      if (blockers.some(b => host.includes(b) || full.includes(b))) return;
      if (
        full.includes('utm_campaign=poweredby') ||
        full.includes('customer-success-stories') ||
        host === 'www.teamtailor.com' ||
        host === 'teamtailor.com' ||
        host === 'app.teamtailor.com' ||
        host === 'recruitee.com' ||
        host === 'www.recruitee.com'
      ) return;
      if (/\/sign-?up|\/login|\/signin|\/register/.test(full)) return;
      // homepages sans path job
      const path = (u.pathname || '/');
      const looksJob = /job|offre|stage|intern|career|recruit|apply|candidat|position|vacanc/i.test(path + u.search);
      const isHard = hardAts.some(p => host.includes(p) || full.includes(p));
      if (!isHard && path.length < 2 && !looksJob) return;
      if (!isHard && /qui-sommes-nous|about-us|contact|privacy|cookie|login|signin/i.test(path) && !looksJob) return;
      urls.push({href, score, label: (label||'').slice(0,80), isHard});
    } catch (e) {}
  };

  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href || '';
    let host = '';
    try { host = new URL(href).hostname.toLowerCase(); } catch(e) { continue; }
    if (!href.startsWith('http')) continue;
    if (blockers.some(b => host.includes(b))) continue;
    const label = ((a.innerText || '') + ' ' + (a.getAttribute('aria-label') || '')).toLowerCase();
    let score = 0;
    const full = href.toLowerCase();
    if (hardAts.some(p => host.includes(p) || full.includes(p))) score += 10;
    if (softCareer.some(p => host.includes(p))) score += 3;
    if (cta.some(c => label.includes(c))) score += 5;
    if (/\/job|\/jobs\/|\/offre|\/stage|\/intern|\/apply/i.test(href)) score += 4;
    if (score > 0) push(href, score, label);
  }

  for (const el of document.querySelectorAll('[data-control-name*="apply"], [data-tracking-control-name*="apply"], a.apply-button, a[href*="externalApply"]')) {
    push(el.href || el.getAttribute('href') || '', 9, 'apply-btn');
  }

  const blob = document.documentElement.innerHTML;
  const keys = ['companyApplyUrl','externalApplyUrl','applyUrl','applicationUrl'];
  for (const k of keys) {
    const re = new RegExp('"' + k + '"\\s*:\\s*"([^"]+)"', 'gi');
    let m;
    while ((m = re.exec(blob)) !== null) {
      let u = m[1].replace(/\\u0026/g,'&').replace(/\\\//g,'/').replace(/&amp;/g,'&');
      try { u = decodeURIComponent(u); } catch(e) {}
      push(u, 12, k);
    }
  }
  const atsRe = /https?:\/\/[^\s"'<>;&]+(?:smartrecruiters\.com|myworkdayjobs\.com|greenhouse\.io|lever\.co|icims\.com|teamtailor\.com|welcometothejungle\.com|successfactors\.com|taleo\.net|ashbyhq\.com|workable\.com|talent-soft\.com|talentsoft\.com|phenompeople\.com)[^\s"'<>]*/gi;
  let am;
  while ((am = atsRe.exec(blob)) !== null) {
    let u = am[0].replace(/\\\//g,'/').replace(/&amp;/g,'&').split('&q;')[0].split('&quot;')[0];
    push(u, 11, 'html-ats');
  }

  urls.sort((a,b) => b.score - a.score);
  // Exiger score minimum : hard ATS ou CTA+job path
  for (const u of urls) {
    if (u.score >= 8 || u.isHard) return u.href;
  }
  return '';
})()
"""
    picked = _eval(ws_url, js)
    if _is_safe_http_url(picked):
        # double-check blockers côté Python
        bad = (
            "apps.apple.com", "play.google.com", "facebook.com", "instagram.com",
            "account.wizbii.com", "wizbii.com/fr_fr/sign-up", "wizbii.com/sign-up",
            "utm_campaign=poweredby", "customer-success-stories", "app.teamtailor.com/login",
        )
        picked = picked.split("&q;")[0].split("&quot;")[0]
        low = picked.lower()
        if any(b in low for b in bad):
            return ""
        # murs d'inscription / login génériques
        if any(x in low for x in ("/sign-up", "/signup", "/login", "/signin", "/register", "auth0.com")):
            if not any(p in low for p in ("myworkdayjobs", "greenhouse", "lever.co", "icims.com", "talent-soft")):
                return ""
        return picked
    return ""




def _stop_browser() -> None:
    global _BROWSER, _BROWSER_PROFILE
    if _BROWSER is not None:
        browser = _BROWSER
        if _BROWSER.poll() is None:
            if os.name == "posix":
                try:
                    os.killpg(browser.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                browser.terminate()
            try:
                browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(browser.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    browser.kill()
                browser.wait(timeout=5)
        _BROWSER = None
    if _BROWSER_PROFILE is not None:
        for attempt in range(5):
            try:
                _BROWSER_PROFILE.cleanup()
                break
            except OSError as exc:
                if exc.errno not in {errno.ENOTEMPTY, errno.EBUSY} or attempt == 4:
                    raise
                time.sleep(0.1)
        _BROWSER_PROFILE = None


def _ensure() -> None:
    global PORT, _BROWSER, _BROWSER_PROFILE, _ATEXIT_REGISTERED
    if _BROWSER is not None and _BROWSER.poll() is None:
        return
    _stop_browser()
    proxy = public_network.browser_proxy()
    _BROWSER_PROFILE = tempfile.TemporaryDirectory(prefix="job-offer-reader-")
    active_port = Path(_BROWSER_PROFILE.name) / "DevToolsActivePort"
    if not _ATEXIT_REGISTERED:
        atexit.register(_stop_browser)
        _ATEXIT_REGISTERED = True
    _BROWSER = subprocess.Popen(
        [
            str(pdfs.browser_path()),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--disable-background-networking",
            "--disable-quic",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            f"--proxy-server={proxy.url}",
            "--proxy-bypass-list=<-loopback>",
            # Navigateur standard : bac à sable conservé, aucun masquage
            # d'automatisation.
            f"--user-agent={USER_AGENT}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
            f"--user-data-dir={_BROWSER_PROFILE.name}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(os.name == "posix"),
    )
    deadline = time.monotonic() + 15.0
    while _BROWSER.poll() is None and time.monotonic() < deadline:
        try:
            port = int(active_port.read_text(encoding="ascii").partition("\n")[0])
            if 1 <= port <= 65535:
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    _LOCAL_HTTP.open(
                        f"http://127.0.0.1:{port}/json/version", timeout=min(0.5, remaining)
                    ).close()
                    PORT = port
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    _stop_browser()
    raise RuntimeError("Chrome ne répond pas pour lire les annonces.")


def _open_tab() -> tuple[str, str]:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new", method="PUT")
    with _LOCAL_HTTP.open(request, timeout=15) as response:
        tab = json.loads(response.read().decode("utf-8"))
    return tab["webSocketDebuggerUrl"], tab["id"]


def _score(text: str) -> int:
    if not text or "403 ERROR" in text or "Request blocked" in text:
        return 0
    folded = text.lower()
    score = min(len(text), 5000)
    for word in ("mission", "profil", "objectif", "compétences", "competences", "nous recherchons"):
        if word in folded:
            score += 500
    if "alerte email" in folded or "alerte e-mail" in folded:
        score -= 400
    return score


def _close_tab(tab_id: str) -> None:
    try:
        _LOCAL_HTTP.open(f"http://127.0.0.1:{PORT}/json/close/{tab_id}", timeout=5).close()
    except Exception:
        return


def _navigate(ws_url: str, url: str) -> None:
    response = _cdp(ws_url, "Page.navigate", {"url": url})
    if response.get("error") or (response.get("result") or {}).get("errorText"):
        raise ConnectionError("Navigation navigateur refusée ou indisponible")


def _wait_text(ws_url: str, minimum: int = 180, timeout: float = 9.8) -> str:
    """Attend le rendu DOM avec polling adaptatif (0.15s puis 0.25s) et détection de stabilisation."""
    expression = "document.body ? document.body.innerText : ''"
    budget = max(0.0, float(timeout))
    deadline = time.monotonic() + budget
    slept = 0.0
    last = ""
    prev = ""
    stable = 0
    poll = 0
    while True:
        remaining = min(deadline - time.monotonic(), budget - slept)
        if remaining <= 0:
            break
        step = 0.15 if poll < 3 else 0.25
        delay = min(step, remaining)
        time.sleep(delay)
        slept += delay
        poll += 1
        last = _eval(ws_url, expression)
        if len(last) >= minimum and "403 ERROR" not in last:
            return last
        if last.strip() and last == prev:
            stable += 1
            if stable >= 3:
                return last
        else:
            stable = 0
        prev = last
    return last


def _eval(ws_url: str, expression: str) -> str:
    message = _cdp(ws_url, "Runtime.evaluate", {"expression": expression, "returnByValue": True})
    return (((message.get("result") or {}).get("result") or {}).get("value")) or ""


def _cdp(ws_url: str, method: str, params: dict | None = None) -> dict:
    parsed = urllib.parse.urlparse(ws_url)
    sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=20)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall(
            (
                f"GET {parsed.path} HTTP/1.1\r\n"
                f"Host: {parsed.hostname}:{parsed.port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        reply = b""
        while b"\r\n\r\n" not in reply:
            piece = sock.recv(1)
            if not piece or len(reply) >= 16384:
                raise ConnectionError("Réponse WebSocket invalide")
            reply += piece
        if not reply.startswith(b"HTTP/1.1 101 "):
            raise ConnectionError("WebSocket refusé")
        _send(sock, json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            message = json.loads(_recv(sock))
            if message.get("id") == 1:
                return message
    finally:
        sock.close()


def _send(sock: socket.socket, text: str) -> None:
    data = text.encode("utf-8")
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", length)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", length)
    header += mask
    sock.sendall(bytes(header) + bytes(byte ^ mask[index % 4] for index, byte in enumerate(data)))


def _recv(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        header = _read(sock, 2)
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", _read(sock, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _read(sock, 8))[0]
        mask = _read(sock, 4) if header[1] & 0x80 else b""
        payload = _read(sock, length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 8:
            raise ConnectionError("websocket fermé")
        if opcode == 1 or opcode == 0:
            chunks.append(payload)
        if header[0] & 0x80 and opcode in (0, 1):
            return b"".join(chunks).decode("utf-8", "replace")


def _read(sock: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        piece = sock.recv(count - len(data))
        if not piece:
            raise ConnectionError("socket fermé")
        data += piece
    return data

"""PDF des CV via Edge ou Chrome, à partir des HTML existants ou générés à la volée."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import candidate_config
from config import CV_HTML, CV_PDF, DATA_DIR
from private_storage import ensure_private_directory, protect_private_file

BROWSER_CANDIDATES = (
    Path("/usr/bin/google-chrome"),
    Path("/usr/bin/chromium"),
    Path("/usr/bin/chromium-browser"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


def _weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401

        return True
    except Exception:
        return False


def browser_path() -> Path:
    if os.getenv("CAREER_PDF_ENGINE", "").strip().lower() == "weasyprint" and _weasyprint_available():
        return Path("weasyprint")
    for cmd in ("google-chrome", "chromium", "chromium-browser", "msedge"):
        p = shutil.which(cmd)
        if p:
            return Path(p)
    for candidate in BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate
    if _weasyprint_available():
        return Path("weasyprint")
    raise FileNotFoundError(
        "Aucun moteur PDF disponible (WeasyPrint, Edge ou Chrome requis)."
    )


def _synthetic_offer_for_key(key: str):
    from hellowork.offer import Offer

    cfg = candidate_config.get_profile()
    if key == "job":
        return Offer(
            id="base-job",
            url="",
            title="Job étudiant — Temps partiel & vacances",
            company="",
            contract="job_etudiant",
            apply_mode="hellowork_job",
        )
    if key == "alternance":
        return Offer(
            id="base-alternance",
            url="",
            title=f"Alternance — {cfg.preset.label}",
            company="",
            contract="alternance",
        )
    return Offer(
        id="base-stage",
        url="",
        title=f"Stage — {cfg.preset.label}",
        company="",
        contract="stage",
    )


def _write_private_html_if_changed(
    target: Path, content: str, *, trusted_root: Path
) -> Path:
    ensure_private_directory(target.parent, trusted_root=trusted_root)
    if target.is_symlink():
        raise ValueError("Fichier HTML candidat symbolique interdit")
    if target.is_file():
        try:
            if target.read_text(encoding="utf-8") == content:
                return target
        except OSError:
            pass
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    protect_private_file(target, trusted_root=trusted_root)
    return target


def _ensure_source_html(
    key: str, configured_html: Path, data_dir: Path
) -> tuple[Path, bool]:
    """Retourne `(chemin_html, est_genere_dynamiquement)`."""
    if configured_html.exists():
        return configured_html, False
    from hellowork import cv_personalize

    offer = _synthetic_offer_for_key(key)
    html_doc, _ = cv_personalize.render_html(offer)
    generated_path = data_dir / f"cv-base-{key}.html"
    return (
        _write_private_html_if_changed(generated_path, html_doc, trusted_root=data_dir),
        True,
    )


def ensure_pdfs() -> dict[str, Path]:
    ensure_private_directory(DATA_DIR, trusted_root=DATA_DIR)
    browser = browser_path()
    ready: dict[str, Path] = {}
    for key, html_file in CV_HTML.items():
        source_html, is_generated = _ensure_source_html(key, html_file, DATA_DIR)
        pdf = CV_PDF[key]
        if is_generated and key == "alternance" and pdf == ready.get("stage"):
            pdf = DATA_DIR / "CV-candidat-Alternance.pdf"
        ensure_private_directory(pdf.parent, trusted_root=pdf.parent)
        if not pdf.exists() or source_html.stat().st_mtime > pdf.stat().st_mtime:
            _print(browser, source_html, pdf)
            if is_generated:
                from hellowork import cv_personalize

                pages = cv_personalize.pdf_page_count(pdf)
                if pages > 1:
                    compact_doc, _ = cv_personalize.render_html_compact(
                        _synthetic_offer_for_key(key)
                    )
                    _write_private_html_if_changed(
                        source_html, compact_doc, trusted_root=DATA_DIR
                    )
                    _print(browser, source_html, pdf)
            protect_private_file(pdf, trusted_root=pdf.parent)
        ready[key] = pdf
    return ready


def html_to_pdf(html: Path, pdf: Path) -> None:
    _print(browser_path(), html, pdf)


def _render_with_weasyprint(html: Path, pdf: Path) -> bool:
    try:
        import weasyprint

        ensure_private_directory(pdf.parent, trusted_root=pdf.parent)
        doc = weasyprint.HTML(filename=str(html))
        try:
            # Tagging structurel PDF/UA-1 (accessibilité & lecture linéaire garantie pour les ATS Workday/SmartRecruiters)
            doc.write_pdf(str(pdf), pdf_tags=True)
        except TypeError:
            doc.write_pdf(str(pdf))
        return pdf.exists() and pdf.stat().st_size > 500
    except Exception:
        return False


def _print(browser: Path, html: Path, pdf: Path) -> None:
    if pdf.exists():
        pdf.unlink()
    ensure_private_directory(DATA_DIR, trusted_root=DATA_DIR)
    if str(browser) == "weasyprint" or not browser.exists():
        if _render_with_weasyprint(html, pdf):
            return
        if str(browser) == "weasyprint":
            raise RuntimeError(f"WeasyPrint n'a pas pu créer {pdf.name}.")
    with tempfile.TemporaryDirectory(prefix="chrome-pdf-", dir=DATA_DIR) as profile_dir:
        profile = Path(profile_dir)
        ensure_private_directory(profile, trusted_root=DATA_DIR)
        command = [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf}",
            html.resolve().as_uri(),
        ]
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=60, check=False
        )
        for _ in range(10):
            if pdf.exists() and pdf.stat().st_size > 1000:
                return
            time.sleep(0.3)
    if _render_with_weasyprint(html, pdf):
        return
    detail = (completed.stderr or completed.stdout or "").strip()[:400]
    raise RuntimeError(f"Le navigateur n'a pas créé {pdf.name}. {detail}")

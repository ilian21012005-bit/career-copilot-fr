"""Zero-hallucination local CV parser (PDF bytes or raw text -> profile v2 draft)."""

from __future__ import annotations

import base64
import binascii
import importlib
import io
import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from career_copilot.sources.deps import SourcesDeps

LOG = logging.getLogger("career_copilot.sources.cv_parser")

_LEVEL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bmaster\s*2\b|\bm2\b|\bbac\s*\+\s*5\b|\bpfe\b|\bcycle\s+ingenieur\b", "Master 2 / Bac+5"),
    (r"\bmaster\s*1\b|\bm1\b|\bbac\s*\+\s*4\b", "Master 1 / Bac+4"),
    (
        r"\bbut\s*3\b|\blicence\s*3\b|\bl3\b|\bbachelor\b|\bbac\s*\+\s*3\b|\bbut\b",
        "Bac+3 / Licence / BUT",
    ),
    (r"\bbts\b|\bdut\b|\bbut\s*2\b|\bl2\b|\bbac\s*\+\s*2\b", "Bac+2 / BTS / BUT 2"),
)

_NAME_NOISE_WORDS: tuple[str, ...] = (
    "curriculum",
    "vitae",
    "stage",
    "alternance",
    "cv",
    "resume",
)


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extract text locally from PDF bytes via ``pdftotext``, ``pypdf``, or literal fallback."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Le fichier fourni n'est pas un document PDF valide.")
    if len(pdf_bytes) > 5 * 1024 * 1024:
        raise ValueError("Le PDF dépasse la taille maximale autorisée (5 Mo).")

    pdftotext_bin = shutil.which("pdftotext")
    if pdftotext_bin:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp_pdf:
            tmp_pdf.write(pdf_bytes)
            tmp_pdf.flush()
            res = subprocess.run(  # noqa: S603
                [pdftotext_bin, "-enc", "UTF-8", tmp_pdf.name, "-"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
    try:
        pypdf = importlib.import_module("pypdf")

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        LOG.debug("Extraction pypdf indisponible: %s", exc)

    chunks = re.findall(rb"\(([^()\\]{3,200})\)", pdf_bytes)
    decoded = " ".join(c.decode("latin-1", errors="ignore") for c in chunks)
    return decoded.strip()


def detect_preset_and_skills(
    folded_text: str,
    preset_hint: str,
    presets_mod: Any,
    fold_fn: Callable[[str], str],
) -> tuple[str, list[str]]:
    """Detect the closest career preset and owned skills strictly from CV text."""
    best_preset_id = (
        preset_hint if preset_hint in presets_mod.CAREER_PRESETS else presets_mod.DEFAULT_PRESET_ID
    )
    best_hits = -1
    matched_skills_by_preset: dict[str, list[str]] = {}
    for pid, preset_obj in presets_mod.CAREER_PRESETS.items():
        hits: list[str] = []
        for sk in preset_obj.skills_weights:
            sk_f = fold_fn(sk)
            if sk_f and re.search(rf"(?<![a-z0-9]){re.escape(sk_f)}(?![a-z0-9])", folded_text):
                hits.append(sk)
        matched_skills_by_preset[pid] = sorted(dict.fromkeys(hits))
        if not preset_hint and len(hits) > best_hits:
            best_hits = len(hits)
            best_preset_id = pid
    return best_preset_id, matched_skills_by_preset.get(best_preset_id, [])


def _extract_candidate_name(lines: list[str], fold_fn: Callable[[str], str]) -> str:
    for ln in lines[:6]:
        if (
            "@" not in ln
            and not re.search(r"\d{2}", ln)
            and 2 <= len(ln.split()) <= 4
            and len(ln) <= 60
            and not any(w in fold_fn(ln) for w in _NAME_NOISE_WORDS)
        ):
            return ln
    return ""


def _extract_level(folded_text: str) -> str:
    for pat, label in _LEVEL_PATTERNS:
        if re.search(pat, folded_text):
            return label
    return ""


def _extract_facts(lines: list[str], email: str, phone: str) -> list[str]:
    facts: list[str] = []
    for ln in lines:
        clean_ln = ln.lstrip("•-*·–— ").strip()
        if 25 <= len(clean_ln) <= 220 and clean_ln not in facts:
            if (email and email in clean_ln) or (phone and phone in clean_ln):
                continue
            facts.append(clean_ln)
        if len(facts) >= 12:
            break
    return facts


def parse_cv_to_profile_draft(
    deps: SourcesDeps,
    *,
    raw_text: str = "",
    pdf_base64: str = "",
    preset_hint: str = "",
) -> dict[str, Any]:
    """Locally parse raw CV text or base64 PDF into a zero-hallucination v2 profile draft."""
    text = (raw_text or "").strip()
    if not text and pdf_base64:
        try:
            raw_b64 = pdf_base64.split(",", 1)[-1].strip()
            pdf_bytes = base64.b64decode(raw_b64, validate=False)
        except (binascii.Error, TypeError, ValueError) as exc:
            raise ValueError("Encodage base64 du PDF invalide.") from exc
        text = extract_text_from_pdf_bytes(pdf_bytes)

    if not text or len(text) < 15:
        raise ValueError("Texte de CV vide ou trop court pour l'extraction.")
    text = text[:30_000]

    email_m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text)
    email = email_m.group(0) if email_m else ""
    phone_m = re.search(r"(?:\+33\s?[1-9]|0[1-9])(?:[\s.\-]?\d{2}){4}", text)
    phone = phone_m.group(0).strip() if phone_m else ""
    linkedin_m = re.search(r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9_\-%/]+", text)
    linkedin = linkedin_m.group(0).replace("http://", "https://").rstrip("/") if linkedin_m else ""
    github_m = re.search(r"https?://(?:www\.)?github\.com/[A-Za-z0-9_\-.]+", text)
    github = github_m.group(0).replace("http://", "https://").rstrip("/") if github_m else ""

    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]
    fold_fn = deps.filters._fold
    folded_text = fold_fn(text)
    name = _extract_candidate_name(lines, fold_fn)
    level = _extract_level(folded_text)
    best_preset_id, detected_skills = detect_preset_and_skills(
        folded_text, preset_hint, deps.presets, fold_fn
    )
    facts = _extract_facts(lines, email, phone)
    inferred_city, _ = deps.source_common.infer_fr_city(text[:400], text[:2000])

    return {
        "ok": True,
        "draft": {
            "preset_id": best_preset_id,
            "candidate": {
                "name": name,
                "email": email,
                "phone": phone,
                "level": level,
                "home": inferred_city,
                "linkedin_url": linkedin,
                "github_url": github,
            },
            "owned_skills": detected_skills,
            "facts": facts,
        },
    }

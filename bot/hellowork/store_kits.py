"""Empreintes de dossiers (kits) et validation documentaire pour hellowork.store."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

_PROFILE_UNREAD = object()

_KIT_OFFER_FIELDS = (
    "url",
    "title",
    "company",
    "city",
    "contract",
    "salary",
    "description",
    "missions",
    "profile",
    "benefits",
    "apply_mode",
)

KIT_SCHEMA_VERSION = 1


def offer_fingerprint(row) -> str:
    payload = [row[field] or "" for field in _KIT_OFFER_FIELDS]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def file_fingerprint(path: Path | str | None) -> str | None:
    """Empreinte bornée d'un fichier ordinaire, sans suivre un lien final."""
    if not path:
        return None
    try:
        file = Path(path)
        if (
            file.is_symlink()
            or not file.is_file()
            or file.stat().st_size > 20 * 1024 * 1024
        ):
            return None
        fd = os.open(file, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 20 * 1024 * 1024:
                return None
            digest = hashlib.sha256()
            size = 0
            for block in iter(lambda: source.read(65536), b""):
                size += len(block)
                if size > 20 * 1024 * 1024:
                    return None
                digest.update(block)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def profile_fingerprint(context) -> str | None:
    """Lie le dossier aux données du profil candidat actif et à la version de schéma."""
    try:
        import candidate_config

        from . import profile

        profile_dict = candidate_config.get_profile().to_dict()
        data = {
            "kit_schema_version": context.KIT_SCHEMA_VERSION,
            "profile": profile_dict,
            "ai_profile": profile.ai_profile(),
            "candidate": dict(profile.CANDIDATE),
        }
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode(
                "utf-8"
            )
        ).hexdigest()
    except (OSError, TypeError, ValueError, AttributeError):
        return None


def save_kit(
    offer_id: str,
    subject: str,
    letter: Path | None,
    cv: Path | None,
    dossier: Path,
    context,
) -> None:
    with context._db() as conn:
        offer = conn.execute(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        fingerprint = context.offer_fingerprint(offer) if offer else None
        conn.execute(
            """
            INSERT INTO kits (offer_id, subject, letter_path, cv_path, dossier_path, created_at, offer_fingerprint, cv_sha256, letter_sha256, profile_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                subject = excluded.subject,
                letter_path = excluded.letter_path,
                cv_path = excluded.cv_path,
                dossier_path = excluded.dossier_path,
                created_at = excluded.created_at,
                offer_fingerprint = excluded.offer_fingerprint,
                cv_sha256 = excluded.cv_sha256,
                letter_sha256 = excluded.letter_sha256,
                profile_fingerprint = excluded.profile_fingerprint
            """,
            (
                offer_id,
                subject,
                str(letter) if letter else "",
                str(cv) if cv else "",
                str(dossier),
                context.now_iso(),
                fingerprint,
                context.file_fingerprint(cv),
                context.file_fingerprint(letter),
                context.profile_fingerprint(),
            ),
        )


def kit_is_current(offer_id: str, kit: dict | None, context) -> bool:
    """A kit is safe to reuse only for the exact offer text it was built from."""
    kit = kit if kit is not None else context.kit_for(offer_id)
    if not kit or not kit.get("offer_fingerprint"):
        return False
    with context._db() as conn:
        offer = conn.execute(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
    return bool(offer and kit["offer_fingerprint"] == context.offer_fingerprint(offer))


def application_offer_ids(offer_ids: list[str], context) -> set[str]:
    """Lit les candidatures d'une liste en une requête, sans modifier leur état."""
    ids = list(dict.fromkeys(str(value) for value in offer_ids if value))
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    with context._db() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT offer_id FROM applications WHERE status != 'withdrawn' AND offer_id IN ({placeholders})",
            ids,
        ).fetchall()
    return {str(row["offer_id"]) for row in rows}


def kit_documents_current(
    kit: dict | None,
    letter_text: str | None,
    context,
    *,
    profile_source=_PROFILE_UNREAD,
) -> bool:
    """Refuse les anciens kits et toute modification des documents ou du profil."""
    if not kit:
        return False
    cv = context.file_fingerprint(kit.get("cv_path"))
    letter = context.file_fingerprint(kit.get("letter_path"))
    profile = (
        context.profile_fingerprint()
        if profile_source is _PROFILE_UNREAD
        else profile_source
    )
    if not (
        cv
        and letter
        and profile
        and cv == kit.get("cv_sha256")
        and letter == kit.get("letter_sha256")
        and profile == kit.get("profile_fingerprint")
    ):
        return False
    if not isinstance(letter_text, str) or not letter_text:
        return False
    try:
        dossier = Path(kit.get("dossier_path") or "")
        if (
            dossier.is_symlink()
            or not dossier.is_file()
            or dossier.stat().st_size > 1024 * 1024
        ):
            return False
        saved = json.loads(dossier.read_text(encoding="utf-8"))
        return (
            saved.get("letter_text_sha256")
            == hashlib.sha256(letter_text.encode("utf-8")).hexdigest()
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def validation_is_current(
    target: dict | str | None,
    context,
    *,
    profile_source=_PROFILE_UNREAD,
) -> bool:
    """Vérifie que la validation de la lettre associée au kit est présente et à jour."""
    if not target:
        return False
    try:
        import offer_letters

        if isinstance(target, str):
            url = target.strip()
            if not url:
                return False
            data = offer_letters.load(url)
        elif isinstance(target, dict):
            if "validation" in target or "letter" in target or "stage" in target:
                data = target
            elif target.get("offer_id"):
                row = context.get(str(target["offer_id"]))
                url = str(row["url"] or "").strip() if row else ""
                data = offer_letters.load(url) if url else None
            else:
                return False
        else:
            return False
        if not isinstance(data, dict):
            return False
        if profile_source is _PROFILE_UNREAD:
            return bool(offer_letters.validation_is_current(data))
        return bool(
            offer_letters.validation_is_current(data, profile_source=profile_source)
        )
    except (ImportError, OSError, TypeError, ValueError, KeyError):
        return False


def _normalize_kit_paths(data: dict, context) -> dict:
    folder = context.DATA_DIR / "hellowork" / "kits" / str(data.get("offer_id") or "")
    for key in ("letter_path", "cv_path", "dossier_path"):
        val = data.get(key)
        if val and not Path(val).exists():
            fname = Path(str(val).replace("\\", "/")).name
            candidate = folder / fname
            if candidate.exists():
                data[key] = str(candidate)
    return data


def kits_for(offer_ids: list[str], context) -> dict[str, dict]:
    """Charge tous les kits en une requête pour éviter un N+1 sur le dashboard."""
    ids = [str(offer_id) for offer_id in offer_ids if offer_id]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with context._db() as conn:
        rows = conn.execute(
            f"SELECT * FROM kits WHERE offer_id IN ({placeholders})", ids
        ).fetchall()
    return {
        str(row["offer_id"]): _normalize_kit_paths(dict(row), context)
        for row in rows
    }

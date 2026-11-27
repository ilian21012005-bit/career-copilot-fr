"""Application kit fingerprinting, storage, and document freshness validation."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from career_copilot.profile import get_profile
from career_copilot.store import offers as offers_mod
from career_copilot.store.connection import DatabaseHandle, now_iso

_PROFILE_UNREAD = object()

KIT_OFFER_FIELDS: tuple[str, ...] = (
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


def offer_fingerprint(row: Any) -> str:
    payload = [row[field] or "" for field in KIT_OFFER_FIELDS]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def file_fingerprint(path: Path | str | None) -> str | None:
    """Bounded SHA-256 fingerprint of a regular non-symlink file (max 20 MiB)."""
    if not path:
        return None
    try:
        file = Path(path)
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 20 * 1024 * 1024:
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


def profile_fingerprint(*, kit_schema_version: int = KIT_SCHEMA_VERSION) -> str | None:
    """Bind kits to active candidate profile data and schema version."""
    try:
        profile_dict = get_profile().to_dict()
        data: dict[str, Any] = {
            "kit_schema_version": kit_schema_version,
            "profile": profile_dict,
        }
        try:
            hw_profile = importlib.import_module("hellowork.profile")

            data["ai_profile"] = hw_profile.ai_profile()
            data["candidate"] = dict(hw_profile.CANDIDATE)
        except ImportError:
            pass
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    except (OSError, TypeError, ValueError, AttributeError):
        return None


def save_kit(
    handle: DatabaseHandle,
    offer_id: str,
    subject: str,
    letter: Path | None,
    cv: Path | None,
    dossier: Path,
    *,
    offer_fp_fn: Callable[[Any], str] = offer_fingerprint,
    file_fp_fn: Callable[[Path | str | None], str | None] = file_fingerprint,
    profile_fp_fn: Callable[[], str | None] = profile_fingerprint,
) -> None:
    with handle.db() as conn:
        offer = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
        fingerprint = offer_fp_fn(offer) if offer else None
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
                now_iso(),
                fingerprint,
                file_fp_fn(cv),
                file_fp_fn(letter),
                profile_fp_fn(),
            ),
        )


def normalize_kit_paths(handle: DatabaseHandle, data: dict[str, Any]) -> dict[str, Any]:
    folder = handle.data_dir / "hellowork" / "kits" / str(data.get("offer_id") or "")
    for key in ("letter_path", "cv_path", "dossier_path"):
        val = data.get(key)
        if val and not Path(val).exists():
            fname = Path(str(val).replace("\\", "/")).name
            candidate = folder / fname
            if candidate.exists():
                data[key] = str(candidate)
    return data


def kits_for(handle: DatabaseHandle, offer_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [str(offer_id) for offer_id in offer_ids if offer_id]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with handle.db() as conn:
        sql = f"SELECT * FROM kits WHERE offer_id IN ({placeholders})"  # noqa: S608
        rows = conn.execute(sql, ids).fetchall()
    return {str(row["offer_id"]): normalize_kit_paths(handle, dict(row)) for row in rows}


def kit_for(handle: DatabaseHandle, offer_id: str) -> dict[str, Any] | None:
    return kits_for(handle, [offer_id]).get(str(offer_id))


def list_kits(handle: DatabaseHandle, *, limit: int = 100) -> list[dict[str, Any]]:
    with handle.db() as conn:
        rows = conn.execute(
            "SELECT * FROM kits ORDER BY created_at DESC LIMIT ?", (max(1, int(limit)),)
        ).fetchall()
    return [normalize_kit_paths(handle, dict(row)) for row in rows]


def kit_is_current(
    handle: DatabaseHandle,
    offer_id: str,
    kit: dict[str, Any] | None = None,
    *,
    offer_fp_fn: Callable[[Any], str] = offer_fingerprint,
) -> bool:
    kit = kit if kit is not None else kit_for(handle, offer_id)
    if not kit or not kit.get("offer_fingerprint"):
        return False
    with handle.db() as conn:
        offer = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    return bool(offer and kit["offer_fingerprint"] == offer_fp_fn(offer))


def application_offer_ids(handle: DatabaseHandle, offer_ids: list[str]) -> set[str]:
    ids = list(dict.fromkeys(str(value) for value in offer_ids if value))
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    with handle.db() as conn:
        sql = f"SELECT DISTINCT offer_id FROM applications WHERE status != 'withdrawn' AND offer_id IN ({placeholders})"  # noqa: S608
        rows = conn.execute(sql, ids).fetchall()
    return {str(row["offer_id"]) for row in rows}


def kit_documents_current(
    kit: dict[str, Any] | None,
    letter_text: str | None = None,
    *,
    profile_source: Any = _PROFILE_UNREAD,
    file_fp_fn: Callable[[Path | str | None], str | None] = file_fingerprint,
    profile_fp_fn: Callable[[], str | None] = profile_fingerprint,
) -> bool:
    if not kit:
        return False
    cv = file_fp_fn(kit.get("cv_path"))
    letter = file_fp_fn(kit.get("letter_path"))
    prof = profile_fp_fn() if profile_source is _PROFILE_UNREAD else profile_source
    if not (
        cv
        and letter
        and prof
        and cv == kit.get("cv_sha256")
        and letter == kit.get("letter_sha256")
        and prof == kit.get("profile_fingerprint")
    ):
        return False
    if not isinstance(letter_text, str) or not letter_text:
        return False
    try:
        dossier = Path(kit.get("dossier_path") or "")
        if dossier.is_symlink() or not dossier.is_file() or dossier.stat().st_size > 1024 * 1024:
            return False
        saved = json.loads(dossier.read_text(encoding="utf-8"))
        return (
            saved.get("letter_text_sha256")
            == hashlib.sha256(letter_text.encode("utf-8")).hexdigest()
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def validation_is_current(
    handle: DatabaseHandle,
    target: dict[str, Any] | str | None,
    *,
    profile_source: Any = _PROFILE_UNREAD,
) -> bool:
    if not target:
        return False
    try:
        offer_letters = importlib.import_module("offer_letters")

        if isinstance(target, str):
            url = target.strip()
            if not url:
                return False
            data = offer_letters.load(url)
        elif isinstance(target, dict):
            if "validation" in target or "letter" in target or "stage" in target:
                data = target
            elif target.get("offer_id"):
                row = offers_mod.get(handle, str(target["offer_id"]))
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
        return bool(offer_letters.validation_is_current(data, profile_source=profile_source))
    except (ImportError, OSError, TypeError, ValueError, KeyError):
        return False

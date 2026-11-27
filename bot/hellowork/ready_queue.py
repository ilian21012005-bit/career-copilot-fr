"""File « prêt à cliquer » : LM + CV prêts, lien apply, aucun envoi auto.

Tu ne fais plus que : ouvrir le lien → vérifier → clic final.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import offer_letters
from config import DATA_DIR
from private_storage import ensure_private_directory, write_private_text

from . import store

LOG = logging.getLogger("hellowork.ready_queue")
MIN_SCORE = 55
SKIP_CAPS = {"dead_partner"}


def apply_url_for(row: dict) -> str:
    partner = (row.get("partner_url") or "").strip()
    if partner and "apps.apple.com" not in partner and "clubmedjobs" not in partner:
        return partner
    return (row.get("url") or "").strip()


def has_ai_letter(url: str) -> bool:
    meta = offer_letters.load(url or "") or {}
    info = str(meta.get("info") or "")
    return bool(meta.get("ai") is True or "Généré par IA" in info)


def ready(limit: int = 40, min_score: int = MIN_SCORE) -> list[dict]:
    """Offres où le dossier est prêt : lettre (+ IA de préférence) + CV + lien."""
    limit = max(0, min(int(limit), 200))
    min_score = max(0, min(int(min_score), 100))
    if limit == 0:
        return []
    store.init()
    out: list[dict] = []
    cursor = None
    batch_size = 100
    sources = store.profile_fingerprint()
    while len(out) < limit:
        rows = [dict(r) for r in store.list_offers(
            min_score=min_score, limit=batch_size, eligible=True, require_kit=True,
            exclude_capabilities=tuple(sorted(SKIP_CAPS)), after=cursor,
        )]
        if not rows:
            break
        # Links and documents may be read after another worker commits a receipt.
        ids = [str(row["id"]) for row in rows]
        kits = store.kits_for(ids)
        applied = store.application_offer_ids(ids)
        letters = offer_letters.load_many([row.get("url") or "" for row in rows])
        out.extend(_ready_batch([row for row in rows if str(row["id"]) not in applied],
                                kits, letters, limit - len(out), sources))
        if len(rows) < batch_size:
            break
        last = rows[-1]
        cursor = (last["score"], last["first_seen"], last["id"])
    return out


def _ready_batch(rows: list[dict], kits: dict, letters: dict, limit: int, sources: str | None) -> list[dict]:
    out = []
    for row in rows:
        kit = kits.get(str(row["id"]))
        # Snapshot d'affichage uniquement ; le chemin d'envoi relit toujours son état.
        if not kit or not kit.get("offer_fingerprint") or kit["offer_fingerprint"] != store.offer_fingerprint(row):
            continue
        letter_ok = bool(kit and kit.get("letter_path") and Path(kit["letter_path"]).is_file())
        cv_ok = bool(kit and kit.get("cv_path") and Path(kit["cv_path"]).is_file())
        if not (letter_ok and cv_ok):
            continue
        validation = letters.get(row.get("url") or "") or {}
        if not isinstance(validation, dict):
            validation = {}
        ai = validation.get("ai") is True or "Généré par IA" in str(validation.get("info") or "")
        content_validated = offer_letters.validation_is_current(validation, profile_source=sources)
        documents_validated = store.kit_documents_current(kit, validation.get("letter"), profile_source=sources)
        blockers = []
        if not content_validated:
            blockers.append("lettre non contrôlée ou périmée")
        if not documents_validated:
            blockers.append("documents ou profil modifiés ou sans empreinte")
        # prêt même sans tag AI si lettre PDF existe (fallback template),
        # mais on flagge ai pour l'UI
        apply_url = apply_url_for(row)
        if not apply_url:
            continue
        out.append(
            {
                "id": row["id"],
                "company": row.get("company"),
                "title": row.get("title"),
                "score": row.get("score"),
                "city": row.get("city") or "",
                "status": row.get("status"),
                "url": row.get("url"),
                "apply_url": apply_url,
                "partner_url": row.get("partner_url") or "",
                "apply_capability": row.get("apply_capability") or "manual_other",
                "has_ai_letter": ai,
                "content_validation_current": content_validated,
                "documents_validation_current": documents_validated,
                "automatic_content_blockers": blockers,
                "ready_to_click": True,
                "letter_path": (kit or {}).get("letter_path") if kit else "",
                "cv_path": (kit or {}).get("cv_path") if kit else "",
            }
        )
        if len(out) >= limit:
            break
    return out


def export_json(path: Path | None = None, *, limit: int = 60) -> Path:
    path = path or (Path(DATA_DIR) / "hellowork" / "ready-to-click.json")
    ensure_private_directory(path.parent)
    data = {"offers": ready(limit=limit), "count": 0}
    data["count"] = len(data["offers"])
    write_private_text(path, json.dumps(data, ensure_ascii=False, indent=2))
    return path

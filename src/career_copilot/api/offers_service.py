"""Offer filtering, serialization, letter/PDF retrieval, and kit listing helpers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from career_copilot.api.runs_service import ApiServiceError
from career_copilot.api.schemas import (
    KitListResponse,
    KitSummary,
    OfferDetail,
    OfferLetterResponse,
    OfferListResponse,
    OfferSummary,
)
from career_copilot.store import DatabaseHandle
from career_copilot.store import kits as kits_store
from career_copilot.store import offers as offers_store

_URL_RE = re.compile(r"https?://[^\s<>'\"()]+", re.IGNORECASE)
_ALTERNANCE_TOKENS = ("alternance", "apprentissage", "professionnalisation", "contrat pro")
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def decode_json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def classify_offer_track(contract: str, title: str) -> tuple[bool, bool]:
    blob = f"{contract} {title}".lower()
    if any(tok in blob for tok in _ALTERNANCE_TOKENS):
        return False, True
    if "job" in contract.lower():
        return False, False
    return ("stage" in blob or "stagiaire" in blob), False


def extract_ats_url(partner_url: str | None, notes: str) -> str | None:
    if partner_url:
        return partner_url
    match = _URL_RE.search(notes or "")
    return match.group(0).rstrip(".,;)") if match else None


def _row_to_offer_fields(row: Any, *, has_kit: bool) -> dict[str, Any]:
    contract = str(row_value(row, "contract", "") or "")
    title = str(row_value(row, "title", "") or "")
    url = str(row_value(row, "url", "") or "")
    partner_raw = str(row_value(row, "partner_url", "") or "").strip() or None
    notes = str(row_value(row, "notes", "") or "")
    is_stage, is_alternance = classify_offer_track(contract, title)
    dist = row_value(row, "distance_km")
    return {
        "id": str(row["id"]),
        "url": url,
        "title": title,
        "company": str(row_value(row, "company", "") or ""),
        "city": str(row_value(row, "city", "") or ""),
        "department": str(row_value(row, "department", "") or ""),
        "contract": contract,
        "salary": str(row_value(row, "salary", "") or ""),
        "score": max(0, min(100, int(row_value(row, "score", 0) or 0))),
        "status": str(row_value(row, "status", "new") or "new"),
        "zone": str(row_value(row, "zone", "") or ""),
        "distance_km": float(dist) if dist is not None else None,
        "location_status": str(row_value(row, "location_status", "unknown") or "unknown"),
        "is_stage": is_stage,
        "is_alternance": is_alternance,
        "apply_capability": str(row_value(row, "apply_capability", "") or ""),
        "contact_email": None,
        "partner_url": partner_raw,
        "apply_url": partner_raw or (url or None),
        "ats_url": extract_ats_url(partner_raw, notes),
        "first_seen": str(row_value(row, "first_seen", "") or ""),
        "last_seen": str(row_value(row, "last_seen", "") or ""),
        "notes": notes,
        "has_kit": has_kit,
        "reasons": decode_json_list(row_value(row, "reasons")),
        "gaps": decode_json_list(row_value(row, "gaps")),
    }


def row_to_offer_summary(row: Any, *, has_kit: bool) -> OfferSummary:
    return OfferSummary(**_row_to_offer_fields(row, has_kit=has_kit))


def row_to_offer_detail(row: Any, *, has_kit: bool) -> OfferDetail:
    fields = _row_to_offer_fields(row, has_kit=has_kit)
    fields.update(
        {
            "posted_at": str(row_value(row, "posted_at", "") or ""),
            "description": str(row_value(row, "description", "") or ""),
            "missions": str(row_value(row, "missions", "") or ""),
            "profile": str(row_value(row, "profile", "") or ""),
            "benefits": str(row_value(row, "benefits", "") or ""),
            "apply_mode": str(row_value(row, "apply_mode", "") or ""),
        }
    )
    return OfferDetail(**fields)


def _letter_key(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:24]


def _safe_data_file(data_dir: Path, raw_path: Path) -> Path | None:
    if raw_path.is_symlink() or not raw_path.is_file():
        return None
    try:
        resolved = raw_path.resolve(strict=True)
        root = data_dir.resolve()
    except OSError:
        return None
    return resolved if resolved.is_relative_to(root) else None


def _matches_offer_filters(
    summary: OfferSummary,
    *,
    track: str | None,
    q: str | None,
    company: str | None,
    exact_company: bool,
) -> bool:
    if track and track.lower() not in ("all", ""):
        wanted = track.lower()
        if wanted == "stage" and not summary.is_stage:
            return False
        if wanted == "alternance" and not summary.is_alternance:
            return False
        if wanted == "job" and (summary.is_stage or summary.is_alternance):
            return False
    if company:
        needle = company.strip().lower()
        cand = summary.company.strip().lower()
        if exact_company and cand != needle:
            return False
        if not exact_company and needle not in cand:
            return False
    if q:
        needle = q.strip().lower()
        hay = " ".join(
            (summary.id, summary.company, summary.title, summary.city, summary.url)
        ).lower()
        if needle not in hay:
            return False
    return True


def list_offers(
    handle: DatabaseHandle,
    *,
    track: str | None = None,
    status: str | None = None,
    q: str | None = None,
    company: str | None = None,
    exact_company: bool | None = None,
    min_score: int | None = None,
    zone: str | None = None,
    eligible: bool = False,
    limit: int = 50,
) -> OfferListResponse:
    bounded = max(1, min(int(limit), 200))
    fetch_limit = 500 if any((track, q, company)) else bounded
    rows = offers_store.list_offers(
        handle,
        status=status,
        min_score=int(min_score) if min_score is not None else 0,
        zone=zone,
        eligible=eligible,
        limit=fetch_limit,
    )
    kit_map = kits_store.kits_for(handle, [str(r["id"]) for r in rows])
    exact = bool(exact_company)
    filtered = [
        item
        for row in rows
        if _matches_offer_filters(
            (item := row_to_offer_summary(row, has_kit=str(row["id"]) in kit_map)),
            track=track,
            q=q,
            company=company,
            exact_company=exact,
        )
    ]
    return OfferListResponse(total=len(filtered), items=filtered[:bounded])


def get_offer_letter(handle: DatabaseHandle, data_dir: Path, offer_id: str) -> OfferLetterResponse:
    row = offers_store.get(handle, offer_id)
    if row is None:
        raise ApiServiceError(404, "Offre introuvable", code="offer_not_found")
    url = str(row["url"] or "").strip()
    if url:
        json_path = _safe_data_file(data_dir, data_dir / "lettres" / f"{_letter_key(url)}.json")
        if json_path is not None:
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            letter_text = str(data.get("letter") or "").strip() if isinstance(data, dict) else ""
            if letter_text:
                mtime = datetime.fromtimestamp(json_path.stat().st_mtime).astimezone()
                return OfferLetterResponse(
                    offer_id=offer_id,
                    letter=letter_text,
                    updated_at=mtime.isoformat(timespec="seconds"),
                )
    kit = kits_store.kit_for(handle, offer_id)
    if kit and kit.get("letter_path"):
        letter_file = _safe_data_file(data_dir, Path(str(kit["letter_path"])))
        if letter_file is not None and letter_file.suffix.lower() in {".txt", ".md"}:
            text = letter_file.read_text(encoding="utf-8").strip()
            if text:
                return OfferLetterResponse(
                    offer_id=offer_id,
                    letter=text,
                    updated_at=str(kit.get("created_at") or "") or None,
                )
    raise ApiServiceError(404, "Lettre introuvable pour cette offre", code="letter_not_found")


def get_offer_letter_pdf(
    handle: DatabaseHandle, data_dir: Path, offer_id: str
) -> tuple[bytes, str]:
    row = offers_store.get(handle, offer_id)
    if row is None:
        raise ApiServiceError(404, "Offre introuvable", code="offer_not_found")
    candidates: list[Path] = []
    kit = kits_store.kit_for(handle, offer_id)
    if kit and kit.get("letter_path"):
        candidates.append(Path(str(kit["letter_path"])))
    url = str(row["url"] or "").strip()
    if url:
        candidates.append(data_dir / "lettres" / f"{_letter_key(url)}.pdf")
    for candidate in candidates:
        safe = _safe_data_file(data_dir, candidate)
        if safe is not None and safe.suffix.lower() == ".pdf":
            safe_id = _SAFE_FILENAME_RE.sub("_", offer_id).strip("._") or "offre"
            return safe.read_bytes(), f"lettre-{safe_id}.pdf"
    raise ApiServiceError(404, "PDF de lettre introuvable", code="letter_pdf_not_found")


def list_kits(
    handle: DatabaseHandle, *, ready_only: bool = False, limit: int = 100
) -> KitListResponse:
    rows = kits_store.list_kits(handle, limit=max(1, min(int(limit), 500)))
    offer_meta: dict[str, tuple[str, str]] = {}
    ids = [str(row["offer_id"]) for row in rows if row.get("offer_id")]
    if ids:
        placeholders = ",".join("?" for _ in ids)
        with handle.db() as conn:
            for offer_row in conn.execute(
                f"SELECT id, company, title FROM offers WHERE id IN ({placeholders})",  # noqa: S608
                ids,
            ):
                offer_meta[str(offer_row["id"])] = (
                    str(offer_row["company"] or ""),
                    str(offer_row["title"] or ""),
                )
    items: list[KitSummary] = []
    for row in rows:
        oid = str(row["offer_id"])
        company, title = offer_meta.get(oid, ("", ""))
        has_cv = bool(row.get("cv_path") and Path(str(row["cv_path"])).is_file())
        has_letter = bool(row.get("letter_path") and Path(str(row["letter_path"])).is_file())
        if ready_only and not (has_cv and has_letter):
            continue
        created = str(row["created_at"] or "")
        items.append(
            KitSummary(
                offer_id=oid,
                company=company,
                title=title,
                subject=str(row["subject"] or ""),
                created_at=created,
                updated_at=created,
                has_cv=has_cv,
                has_letter=has_letter,
                has_dossier=bool(
                    row.get("dossier_path") and Path(str(row["dossier_path"])).is_file()
                ),
                is_current=kits_store.kit_is_current(handle, oid, kit=row),
            )
        )
    return KitListResponse(total=len(items), items=items)

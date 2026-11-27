"""Batch IDF offer preparation and Sprint ATS queue construction."""

from __future__ import annotations

from typing import Any

from career_copilot.assist.ats_adapters import resolve_target_url
from career_copilot.assist.deps import AssistDeps, offer_from_row_safe, row_get
from career_copilot.assist.email_extract import extract_public_recruiter_email, is_idf_offer
from career_copilot.assist.prefill import build_prefill_payload


def batch_prepare_idf(deps: AssistDeps, min_score: int = 68, limit: int = 10) -> dict[str, Any]:
    """Batch-prepare ``new`` IDF offers scoring at or above ``min_score``."""
    deps.store.init()
    rows = deps.store.list_offers(status="new")
    eligible = [
        row
        for row in rows
        if is_idf_offer(row) and int(row_get(row, "score") or 0) >= int(min_score)
    ]
    eligible.sort(key=lambda r: int(row_get(r, "score") or 0), reverse=True)
    selected = eligible[: max(1, int(limit))]

    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    emails_found = 0

    for row in selected:
        offer_obj = deps.offers.from_row(row)
        result = deps.scoring.evaluate(offer_obj)
        deps.store.save_offer(offer_obj, result)
        try:
            files = deps.kit.build(offer_obj, result)
        except ValueError as exc:
            errors.append(
                {
                    "offer_id": str(row["id"]),
                    "company": str(row_get(row, "company") or ""),
                    "error": str(exc),
                }
            )
            continue

        deps.store.save_kit(
            row["id"],
            files["subject"],
            files["letter"],
            files["cv"],
            files["dossier"],
        )
        deps.store.set_status(row["id"], "prepared")
        recruiter_email = extract_public_recruiter_email(
            row_get(row, "description", ""),
            row_get(row, "missions", ""),
            row_get(row, "profile", ""),
            row_get(row, "notes", ""),
        )
        if recruiter_email:
            emails_found += 1
        items.append(
            {
                "offer_id": str(row["id"]),
                "company": str(row_get(row, "company") or ""),
                "title": str(row_get(row, "title") or ""),
                "score": int(result.value),
                "recruiter_email": recruiter_email,
                "cv": str(files.get("cv") or ""),
                "letter": str(files.get("letter") or ""),
                "dossier": str(files.get("dossier") or ""),
            }
        )

    return {
        "ok": True,
        "min_score": int(min_score),
        "eligible_count": len(eligible),
        "prepared_count": len(items),
        "skipped_count": max(0, len(eligible) - len(selected)),
        "emails_found": emails_found,
        "items": items,
        "errors": errors,
    }


def sprint_sort_key(row: dict[str, Any]) -> tuple[int, int, int, str]:
    """Rank external ATS offers ahead of HelloWork auto-apply offers, then by score."""
    cap = str(row.get("apply_capability") or "").strip()
    if cap == "manual_partner":
        tier, sub = 0, 0
    elif cap == "manual_other":
        tier, sub = 0, 1
    elif cap == "auto_hellowork":
        tier, sub = 2, 0
    else:
        tier, sub = 1, 0
    return (tier, -int(row.get("score") or 0), sub, str(row.get("id") or ""))


def build_sprint_item(row: dict[str, Any], kit_data: Any, deps: AssistDeps) -> dict[str, Any]:
    """Format an external offer row for the Sprint ATS panel."""
    payload = build_prefill_payload(row, kit_data, deps)
    letter_text = payload["letter_text"]
    letter_preview = " ".join(letter_text.split())[:240] if letter_text else ""
    has_kit = bool(
        kit_data
        and (
            payload["files"]["cv"]
            or payload["files"]["letter"]
            or kit_data.get("cv_path")
            or kit_data.get("letter_path")
        )
    )
    return {
        "offer_id": str(row["id"]),
        "company": str(row.get("company") or ""),
        "title": str(row.get("title") or ""),
        "score": int(row.get("score") or 0),
        "city": str(row.get("city") or ""),
        "status": str(row.get("status") or ""),
        "ats": payload["ats"],
        "ats_adapter": payload["ats_adapter"],
        "apply_capability": str(row.get("apply_capability") or "manual_other"),
        "target_url": payload["target_url"],
        "recruiter_email": payload["recruiter_email"],
        "has_kit": has_kit,
        "letter_preview": letter_preview,
        "letter_text": letter_text,
        "answers": payload["answers"],
        "cv_path": payload["files"]["cv"],
        "letter_path": payload["files"]["letter"],
    }


def _select_sprint_candidates(
    raw_rows: list[dict[str, Any]],
    applied_ids: set[str],
    bound_score: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in raw_rows:
        oid = str(row.get("id") or "")
        if not oid or oid in applied_ids:
            continue
        if str(row.get("status") or "") not in ("new", "shortlist", "prepared"):
            continue
        if str(row.get("apply_capability") or "").strip() == "dead_partner":
            continue
        if int(row.get("score") or 0) < bound_score:
            continue
        if not resolve_target_url(row).startswith(("http://", "https://")):
            continue
        candidates.append(row)
    candidates.sort(key=sprint_sort_key)
    return candidates


def _prepare_sprint_row(
    row: dict[str, Any],
    deps: AssistDeps,
) -> tuple[Any | None, dict[str, str] | None]:
    oid = str(row["id"])
    offer_obj = offer_from_row_safe(row, deps.offers.Offer)
    result = deps.scoring.evaluate(offer_obj)
    try:
        files = deps.kit.build(offer_obj, result)
    except ValueError as exc:
        return None, {
            "offer_id": oid,
            "company": str(row.get("company") or ""),
            "error": str(exc),
        }
    deps.store.save_kit(oid, files["subject"], files["letter"], files["cv"], files["dossier"])
    deps.store.set_status(oid, "prepared")
    row["status"] = "prepared"
    kit_data = deps.store.kit_for(oid) or {
        "cv_path": str(files.get("cv") or ""),
        "letter_path": str(files.get("letter") or ""),
    }
    return kit_data, None


def build_sprint_queue(
    deps: AssistDeps,
    limit: int = 15,
    min_score: int = 65,
    auto_prepare: bool = False,
) -> dict[str, Any]:
    """Build the Sprint ATS queue of external offers ready for 1-click assisted prefill."""
    bound_limit = max(1, min(int(limit), 50))
    bound_score = max(0, min(int(min_score), 100))

    deps.store.init()
    raw_rows = [
        dict(r)
        for r in deps.store.list_offers(
            eligible=True,
            min_score=bound_score,
            exclude_capabilities=("dead_partner",),
            limit=500,
        )
    ]
    ids = [str(r.get("id") or "") for r in raw_rows if r.get("id")]
    applied_ids = deps.store.application_offer_ids(ids) if ids else set()
    candidates = _select_sprint_candidates(raw_rows, applied_ids, bound_score)
    selected = candidates[:bound_limit]

    selected_ids = [str(r["id"]) for r in selected]
    kits_map = deps.store.kits_for(selected_ids) if selected_ids else {}

    prepared_now = 0
    errors: list[dict[str, str]] = []
    items: list[dict[str, Any]] = []

    for row in selected:
        oid = str(row["id"])
        kit_data = kits_map.get(oid)
        is_current = bool(kit_data and deps.store.kit_is_current(oid, kit_data))
        if auto_prepare and not is_current and prepared_now < 5:
            new_kit, err = _prepare_sprint_row(row, deps)
            if err is not None:
                errors.append(err)
            else:
                kit_data = new_kit
                prepared_now += 1
        items.append(build_sprint_item(row, kit_data, deps))

    return {
        "ok": True,
        "min_score": bound_score,
        "limit": bound_limit,
        "total_eligible": len(candidates),
        "prepared_now": prepared_now,
        "items": items,
        "errors": errors,
    }

"""Daily queue selection, balanced bucketing, and kit preparation."""

from __future__ import annotations

from typing import Any

from career_copilot.daily.deps import (
    BUCKET_ORDER,
    MAX_PER_COMPANY_IN_PLAN,
    TRACK_BUCKETS,
    DailyDeps,
)

Fingerprint = tuple[str, str, set[str]]


def row_fingerprint(deps: DailyDeps, row: Any) -> Fingerprint | None:
    comp_norm = deps.dedup.normalize_company(row["company"] or "")
    toks = deps.dedup.title_tokens(row["title"] or "")
    if not comp_norm or not toks:
        return None
    city_norm = deps.dedup.normalize_city(row["city"] or "")
    return (comp_norm, city_norm, toks)


def is_duplicate_of_any(
    deps: DailyDeps,
    fp: Fingerprint | None,
    fingerprints: list[Fingerprint],
    *,
    threshold: float = 0.55,
) -> bool:
    if fp is None:
        return False
    comp_norm, city_norm, toks = fp
    for other_comp, other_city, other_toks in fingerprints:
        if other_comp != comp_norm:
            continue
        if not deps.dedup._cities_compatible(city_norm, other_city):
            continue
        if deps.dedup._jaccard(toks, other_toks) >= threshold:
            return True
    return False


def offer_bucket(deps: DailyDeps, row: Any) -> str:
    offer = deps.offers.from_row(row)
    if deps.scoring.campaign_of(offer) == "job":
        return "job_etudiant"
    track = deps.cv_personalize.detect_track(offer)
    return TRACK_BUCKETS.get(track, "support_ops")


class _SelectionState:
    def __init__(self, deps: DailyDeps, existing: list[Any]) -> None:
        self.deps = deps
        self.chosen: list[Any] = []
        self.chosen_ids: set[str] = set()
        self.counts: dict[str, int] = {bucket: 0 for bucket in BUCKET_ORDER}
        self.seen_fps: list[Fingerprint] = []
        self.company_counts: dict[str, int] = {}
        for row in existing:
            self._record_existing(row)

    def _record_existing(self, row: Any) -> None:
        bucket = offer_bucket(self.deps, row)
        self.counts[bucket] = self.counts.get(bucket, 0) + 1
        fp = row_fingerprint(self.deps, row)
        if fp is not None:
            self.seen_fps.append(fp)
            self.company_counts[fp[0]] = self.company_counts.get(fp[0], 0) + 1

    def can_take(self, row: Any, *, enforce_company_cap: bool = True) -> bool:
        if row["id"] in self.chosen_ids:
            return False
        fp = row_fingerprint(self.deps, row)
        if is_duplicate_of_any(self.deps, fp, self.seen_fps):
            return False
        return not (
            enforce_company_cap
            and fp is not None
            and self.company_counts.get(fp[0], 0) >= MAX_PER_COMPANY_IN_PLAN
        )

    def take(self, row: Any) -> None:
        self.chosen.append(row)
        self.chosen_ids.add(row["id"])
        self._record_existing(row)


def _bucket_soft_capped(
    bucket: str,
    counts: dict[str, int],
    queues: dict[str, list[Any]],
    *,
    cyber_soft_cap: int,
    job_soft_cap: int,
) -> bool:
    if bucket == "cyber_soc" and counts.get(bucket, 0) >= cyber_soft_cap:
        return any(
            queues[other] for other in BUCKET_ORDER if other not in ("cyber_soc", "job_etudiant")
        )
    if bucket == "job_etudiant" and counts.get(bucket, 0) >= job_soft_cap:
        return any(queues[other] for other in BUCKET_ORDER if other != "job_etudiant")
    return False


def _pick_auto_candidates(
    deps: DailyDeps,
    state: _SelectionState,
    auto_candidates: list[Any],
    *,
    room: int,
    job_soft_cap: int,
    has_stage_candidates: bool,
) -> None:
    for row in auto_candidates:
        if len(state.chosen) >= room:
            return
        if not state.can_take(row, enforce_company_cap=True):
            continue
        bucket = offer_bucket(deps, row)
        if (
            bucket == "job_etudiant"
            and state.counts.get("job_etudiant", 0) >= job_soft_cap
            and has_stage_candidates
        ):
            continue
        state.take(row)


def _pick_round_robin(
    state: _SelectionState,
    queues: dict[str, list[Any]],
    *,
    room: int,
    cyber_soft_cap: int,
    job_soft_cap: int,
) -> None:
    while len(state.chosen) < room:
        progressed = False
        ordered_buckets = sorted(
            BUCKET_ORDER, key=lambda b: (state.counts.get(b, 0), BUCKET_ORDER.index(b))
        )
        for bucket in ordered_buckets:
            if not queues[bucket] or _bucket_soft_capped(
                bucket,
                state.counts,
                queues,
                cyber_soft_cap=cyber_soft_cap,
                job_soft_cap=job_soft_cap,
            ):
                continue
            while queues[bucket]:
                row = queues[bucket].pop(0)
                if state.can_take(row, enforce_company_cap=True):
                    state.take(row)
                    progressed = True
                    break
            if len(state.chosen) >= room:
                return
        if not progressed:
            return


def select_balanced(
    deps: DailyDeps,
    prepared: list[Any],
    remaining: list[Any],
    existing: list[Any],
    room: int,
    goal: int,
) -> list[Any]:
    if room <= 0:
        return []
    state = _SelectionState(deps, existing)
    job_soft_cap = max(4, goal // 2)
    auto_candidates = [
        row
        for row in [*remaining, *prepared]
        if str(row["apply_capability"] or "") == "auto_hellowork"
    ]
    has_stage_candidates = any(
        offer_bucket(deps, row) != "job_etudiant" for row in [*remaining, *prepared]
    )
    _pick_auto_candidates(
        deps,
        state,
        auto_candidates,
        room=room,
        job_soft_cap=job_soft_cap,
        has_stage_candidates=has_stage_candidates,
    )
    if len(state.chosen) >= room:
        return state.chosen

    pool = [row for row in remaining if row["id"] not in state.chosen_ids]
    queues: dict[str, list[Any]] = {bucket: [] for bucket in BUCKET_ORDER}
    for row in pool:
        queues[offer_bucket(deps, row)].append(row)

    _pick_round_robin(
        state,
        queues,
        room=room,
        cyber_soft_cap=max(2, (goal * 2 + 4) // 5),
        job_soft_cap=job_soft_cap,
    )
    if len(state.chosen) < room:
        for row in [*auto_candidates, *pool, *prepared]:
            if state.can_take(row, enforce_company_cap=True):
                state.take(row)
                if len(state.chosen) >= room:
                    break
    return state.chosen


def _refresh_scores(deps: DailyDeps) -> None:
    geocode_attempts = 0
    for row in deps.store.list_offers(min_score=0, limit=500):
        if row["status"] not in ("new", "shortlist", "prepared"):
            continue
        offer = deps.offers.from_row(row)
        if offer.latitude is not None and offer.longitude is not None:
            deps.geo.resolve(offer)
        elif offer.city and geocode_attempts < 20:
            deps.geo.resolve(offer)
            geocode_attempts += 1
        result = deps.scoring.evaluate(offer)
        if result.value != row["score"] or offer.location_status != row["location_status"]:
            deps.store.save_offer(offer, result)


def _eligible_candidates(
    deps: DailyDeps,
    *,
    zone: str | None,
    existing_ids: set[str],
) -> list[Any]:
    rows = deps.store.list_offers(
        min_score=deps.profile.AUTO_HELLOWORK_MIN_SCORE,
        limit=500,
        zone=zone,
        location="in_zone",
        eligible=True,
        exclude_capabilities=("dead_partner",),
    )
    applied_fps = [
        fp
        for fp in (
            row_fingerprint(deps, r)
            for r in deps.store.list_offers(status="applied", min_score=0, limit=500)
        )
        if fp is not None
    ]
    candidates: list[Any] = []
    for row in rows:
        if row["status"] not in ("new", "shortlist", "prepared") or row["id"] in existing_ids:
            continue
        if is_duplicate_of_any(deps, row_fingerprint(deps, row), applied_fps):
            continue
        row_cap = str(row["apply_capability"] or "")
        if int(row["score"] or 0) >= deps.profile.MIN_SCORE:
            candidates.append(row)
            continue
        if row_cap == "auto_hellowork":
            offer_obj = deps.offers.from_row(row)
            if deps.scoring.is_eligible_for_plan(
                deps.scoring.evaluate(offer_obj),
                row_cap,
                campaign=deps.scoring.campaign_of(offer_obj),
            ):
                candidates.append(row)
    candidates.sort(
        key=lambda r: (
            0 if str(r["apply_capability"] or "") == "auto_hellowork" else 1,
            -int(r["score"] or 0),
        )
    )
    return candidates


def build(
    deps: DailyDeps,
    target: int | None = None,
    cap: int | None = None,
    zone: str | None = None,
) -> list[Any]:
    """Fill today's plan up to `cap` without emptying existing selections."""
    deps.store.init()
    deps.store.cleanup_stale_planned()
    resolved_cap = cap or deps.profile.DAILY_MAX
    goal = resolved_cap if target is None else min(max(0, target), resolved_cap)
    raw_existing = deps.store.plan_for()
    existing = [
        row
        for row in raw_existing
        if row["status"] not in ("ignored", "to_finish", "submission_unknown")
        and row["plan_status"] not in ("skipped", "to_finish", "submission_unknown")
    ]
    existing_ids = {row["id"] for row in raw_existing}
    room = max(0, goal - len(existing))
    if room > 0:
        _refresh_scores(deps)
        candidates = _eligible_candidates(deps, zone=zone, existing_ids=existing_ids)
        prepared = [row for row in candidates if row["status"] == "prepared"]
        remaining = [row for row in candidates if row["status"] != "prepared"]
        new_rows = select_balanced(deps, prepared, remaining, existing, room, goal)
        if new_rows:
            deps.store.set_plan([row["id"] for row in existing] + [row["id"] for row in new_rows])
            existing = deps.store.plan_for()
    return existing


def prepare(deps: DailyDeps, limit: int | None = None) -> list[dict[str, Any]]:
    """Generate kits for planned offers that do not yet have a current validated kit."""
    made: list[dict[str, Any]] = []
    for row in deps.store.plan_for()[: limit or None]:
        if deps.store.has_application(row["id"]):
            if deps.store.has_sent_application(row["id"]):
                deps.store.set_status(row["id"], "applied")
            continue
        existing_kit = deps.store.kit_for(row["id"])
        if existing_kit and deps.store.kit_is_current(row["id"], existing_kit):
            url = str(dict(row).get("url") or "").strip()
            letter_meta = None
            if url:
                try:
                    letter_meta = deps.offer_letters.load(url)
                except (OSError, ValueError, TypeError):
                    letter_meta = None
            letter_text = letter_meta.get("letter") if isinstance(letter_meta, dict) else None
            if deps.store.kit_documents_current(
                existing_kit, letter_text
            ) and deps.store.validation_is_current(letter_meta):
                continue
        offer = deps.offers.from_row(row)
        if offer.latitude is None or offer.longitude is None:
            deps.geo.resolve(offer)
        result = deps.scoring.evaluate(offer)
        deps.store.save_offer(offer, result)
        try:
            files = deps.kit.build(offer, result)
        except ValueError as exc:
            print(f"  ! {row['company']} — {exc}")
            continue
        deps.store.save_kit(
            row["id"], files["subject"], files["letter"], files["cv"], files["dossier"]
        )
        if str(row["status"] or "") in ("new", "shortlist", "prepared"):
            deps.store.set_status(row["id"], "prepared")
        made.append({"row": row, "files": files})
    return made


def remaining_today(deps: DailyDeps) -> int:
    plan = deps.store.plan_for()
    done = sum(1 for row in plan if row["plan_status"] in ("applied", "skipped"))
    return max(0, deps.profile.DAILY_TARGET - done)

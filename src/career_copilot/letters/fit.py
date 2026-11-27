"""Deterministic A-F offer fit scoring and fact-grounded profile paragraphs."""

from __future__ import annotations

import re

from career_copilot.letters.formatting import is_candidate_bac3_or_less
from career_copilot.letters.text_utils import (
    FACT_STOPWORDS,
    fold,
    french,
    has_word,
    is_alternance_text,
    join_fr,
)
from career_copilot.profile import CandidateProfileConfig


def skill_owned(kw_folded: str, owned_folded: set[str]) -> bool:
    if not owned_folded:
        return True
    if kw_folded in owned_folded:
        return True
    return any(len(sk) >= 3 and (kw_folded in sk or sk in kw_folded) for sk in owned_folded)


def compute_fit_gaps(folded_offer: str, cfg: CandidateProfileConfig, campaign: str) -> list[str]:
    gaps: list[str] = []
    cand_level = str(cfg.candidate.get("level") or "Bac+3").strip()
    if is_candidate_bac3_or_less(cfg):
        if "bac+5" in folded_offer or "bac +5" in folded_offer:
            gaps.append(f"Niveau Bac+5 demandé (profil {cand_level})")
        if "master" in folded_offer:
            gaps.append(f"Niveau Master demandé (profil {cand_level})")
    if (
        "alternance" in folded_offer
        and campaign != "alternance"
        and "alternance" not in cfg.contracts
    ):
        weeks = cfg.candidate.get("weeks") or 16
        gaps.append(f"Offre formulée en alternance (cible stage {weeks} sem.)")
    if any(
        marker in folded_offer
        for marker in (
            "5 ans d'experience",
            "5 ans d’experience",
            "3 ans d'experience",
            "3 ans d’experience",
        )
    ):
        gaps.append("Expérience senior demandée")
    return gaps


def compute_offer_fit(
    cfg: CandidateProfileConfig,
    title: str,
    source_text: str,
    *,
    stage: bool = True,
    campaign: str | None = None,
) -> dict[str, object]:
    """Deterministic A-F profile/offer fit grid (zero invented skills)."""
    resolved = campaign or (
        "job" if not stage else ("alternance" if is_alternance_text(title) else "stage")
    )
    if resolved == "job" or not stage:
        jp = cfg.job_profile or {}
        ctx = str(jp.get("retail_context") or "en commerce et relation client").strip()
        tasks = [str(t) for t in (jp.get("confirmed_tasks") or [])[:2] if str(t).strip()]
        detail = f" ({', '.join(tasks)})" if tasks else ""
        return {
            "grade": "B",
            "score": 70,
            "matched": [f"Relation client & polyvalence {ctx}{detail}".strip()],
            "gaps": [],
        }

    folded = fold(f"{title}\n{source_text}")
    owned_folded = {fold(skill) for skill in cfg.owned_skills}
    matched: list[str] = []
    matched_count = 0
    for _group_key, keywords, group_label in cfg.preset.fit_groups:
        folded_kws = tuple(fold(kw) for kw in keywords)
        if any(kw in folded for kw in folded_kws) and any(
            skill_owned(kw, owned_folded) for kw in folded_kws
        ):
            matched_count += 1
            if group_label not in matched:
                matched.append(group_label)

    if not matched and owned_folded:
        direct = sorted(
            (skill for skill in cfg.owned_skills if has_word(folded, skill)),
            key=lambda s: (-cfg.skills_weights.get(s, 1), s),
        )
        if direct:
            matched_count = min(3, len(direct))
            matched.append(f"Compétences : {', '.join(direct[:4])}")

    gaps = compute_fit_gaps(folded, cfg, resolved)
    ratio = 55 if matched_count == 0 else min(95, 50 + matched_count * 12)
    score = max(15, ratio - 18 * len(gaps))
    grade = (
        "A"
        if score >= 82
        else "B"
        if score >= 68
        else "C"
        if score >= 52
        else "D"
        if score >= 36
        else "F"
    )
    return {"grade": grade, "score": score, "matched": matched[:5], "gaps": gaps[:4]}


def relevance_score(blob: str, folded_offer: str, offer_tokens: set[str]) -> int:
    folded_blob = fold(blob)
    words = {
        word for word in re.findall(r"[a-z0-9+#.-]{3,}", folded_blob) if word not in FACT_STOPWORDS
    }
    score = sum(2 for word in words if word in offer_tokens)
    score += sum(1 for word in words if len(word) >= 4 and word in folded_offer)
    return score


def render_experiences_and_projects(
    cfg: CandidateProfileConfig,
    folded_offer: str,
    offer_tokens: set[str],
) -> list[str]:
    parts: list[str] = []
    ranked_exps = sorted(
        enumerate(cfg.experiences),
        key=lambda item: (
            -relevance_score(
                " ".join(
                    [
                        str(item[1].get("role") or ""),
                        str(item[1].get("company") or ""),
                        " ".join(item[1].get("tags") or ()),
                        " ".join(item[1].get("bullets") or ()),
                    ]
                ),
                folded_offer,
                offer_tokens,
            ),
            item[0],
        ),
    )
    for _idx, exp in ranked_exps[:2]:
        role = str(exp.get("role") or "").strip()
        comp = str(exp.get("company") or "").strip()
        bullets = [str(b).strip().rstrip(".") for b in (exp.get("bullets") or []) if str(b).strip()]
        ranked_bullets = sorted(
            enumerate(bullets),
            key=lambda item: (-relevance_score(item[1], folded_offer, offer_tokens), item[0]),
        )
        chosen = [bullet for _, bullet in ranked_bullets[:2]]
        where = (
            f"En tant que {role} chez {comp}"
            if role and comp
            else f"Chez {comp}"
            if comp
            else f"En tant que {role}"
            if role
            else "Lors d’une précédente expérience"
        )
        if chosen:
            parts.append(f"{where}, j’ai notamment mené : {' ; '.join(chosen)}.")
        elif role or comp:
            parts.append(f"{where}, j’ai consolidé mes compétences opérationnelles sur le terrain.")

    ranked_projs = sorted(
        enumerate(cfg.projects),
        key=lambda item: (
            -relevance_score(
                " ".join(
                    [
                        str(item[1].get("name") or ""),
                        str(item[1].get("summary") or ""),
                        " ".join(item[1].get("tags") or ()),
                    ]
                ),
                folded_offer,
                offer_tokens,
            ),
            item[0],
        ),
    )
    proj_clauses: list[str] = []
    for _idx, proj in ranked_projs[:2]:
        name = str(proj.get("name") or "").strip()
        summary = str(proj.get("summary") or "").strip().rstrip(".")
        if name and summary:
            proj_clauses.append(f"{name} ({summary})")
        elif name or summary:
            proj_clauses.append(name or summary)
    if proj_clauses:
        parts.append(f"Côté projets, j’ai réalisé {join_fr(proj_clauses)}.")
    return parts


def select_relevant_facts(
    facts: tuple[str, ...],
    folded_offer: str,
    offer_tokens: set[str],
    limit: int = 3,
) -> list[str]:
    ranked = sorted(
        enumerate(facts),
        key=lambda item: (-relevance_score(item[1], folded_offer, offer_tokens), item[0]),
    )
    selected: list[str] = []
    for _idx, raw_fact in ranked[:limit]:
        cleaned = french(str(raw_fact).strip())
        if not cleaned:
            continue
        if not cleaned.endswith((".", "!", "?")):
            cleaned += "."
        selected.append(cleaned[0].upper() + cleaned[1:])
    return selected


def stage_profile(cfg: CandidateProfileConfig, source: str) -> str:
    folded = fold(source)
    offer_tokens = {
        word for word in re.findall(r"[a-z0-9+#.-]{3,}", folded) if word not in FACT_STOPWORDS
    }
    parts: list[str] = []

    if cfg.experiences or cfg.projects:
        parts.extend(render_experiences_and_projects(cfg, folded, offer_tokens))
    elif cfg.facts:
        parts.extend(select_relevant_facts(cfg.facts, folded, offer_tokens, limit=3))
    else:
        common_skills = sorted(
            (skill for skill in cfg.owned_skills if has_word(folded, skill)),
            key=lambda s: (-cfg.skills_weights.get(s, 1), s),
        )
        if common_skills:
            parts.append(
                f"Ma formation orientée {cfg.preset.label} m’a permis de pratiquer "
                f"{join_fr(common_skills[:5])}, compétences que je souhaite mobiliser concrètement au sein de votre équipe."
            )
        else:
            core_owned = [skill for skill in cfg.preset.core_skills if skill in cfg.owned_skills][
                :4
            ]
            skills_hint = f" ({join_fr(core_owned)})" if core_owned else ""
            parts.append(
                f"Ma formation orientée {cfg.preset.label} m’apporte des bases solides{skills_hint} "
                "que je souhaite mettre en pratique avec rigueur au sein de votre équipe."
            )

    if is_candidate_bac3_or_less(cfg) and any(
        word in folded
        for word in (
            "bac +5",
            "bac+5",
            "bac+4/5",
            "master",
            "ecole d'ingenieur",
            "ecole d ingenieur",
        )
    ):
        cand_level = str(cfg.candidate.get("level") or "Bac+3").strip()
        parts.append(
            f"Je candidate depuis un cursus {cand_level} (et non un Bac+5), en toute transparence "
            "sur mon niveau actuel et avec l’envie de monter rapidement en compétence."
        )
    if "habilitation" in folded or "secret de la defense" in folded:
        parts.append(
            "Si une habilitation est nécessaire pour ce poste, je suivrai la procédure prévue."
        )
    return " ".join(parts)

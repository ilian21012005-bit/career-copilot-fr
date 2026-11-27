"""HTML section builders for ATS-compliant personalized CVs."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from career_copilot.cv.styles import (
    GUARDRAIL_FACT_PREFIXES,
    MONTHS_SHORT_FR,
    UPPER_ACRONYMS,
)
from career_copilot.cv.tracks import fold_text, keyword_present


def escape_html(text: object) -> str:
    """HTML-escape any value with quote escaping enabled."""
    return html.escape(str(text or ""), quote=True)


def short_url(url: str) -> str:
    """Strip scheme, ``www.``, and trailing slash for compact CV link labels."""
    return re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/")


def parse_date_safe(raw: Any, fallback: date) -> date:
    """Parse an ISO date or ``date`` instance with safe fallback."""
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str) and len(raw.strip()) >= 10:
        try:
            return date.fromisoformat(raw.strip()[:10])
        except ValueError:
            return fallback
    return fallback


def pretty_skill(skill: str) -> str:
    """Format a normalized skill slug for display while preserving known acronyms."""
    clean = skill.strip()
    low = clean.lower()
    if low in UPPER_ACRONYMS:
        return low.upper()
    if "." in clean or "/" in clean:
        return clean[0].upper() + clean[1:] if clean else clean
    return clean.capitalize()


def resolve_mobility(cfg: Any, *, is_job: bool) -> str:
    """Format candidate geographic mobility for internships, apprenticeships, or student jobs."""
    cand_mob = str(cfg.candidate.get("mobility") or "").strip()
    if is_job:
        job_mob = str(
            cfg.job_form_answers.get("Mobilité") or cfg.job_form_answers.get("mobilité") or ""
        ).strip()
        if job_mob:
            return job_mob
        city = str(cfg.candidate.get("home") or (cfg.zones[0]["name"] if cfg.zones else "")).strip()
        km = f"{float(cfg.job_radius_km):g} km"
        return f"{city} ({km})" if city else f"Rayon {km}"
    if cand_mob:
        return cand_mob
    if cfg.zones:
        names = " · ".join(str(z.get("name") or "").strip() for z in cfg.zones if z.get("name"))
        max_km = max((float(z.get("km", 30.0)) for z in cfg.zones), default=30.0)
        if names:
            return f"{names} ({max_km:g} km)"
    return "France"


def render_header(cfg: Any) -> str:
    """Render the CV top header with candidate identity, education subtitle, and contact links."""
    cand = cfg.candidate
    name = str(cand.get("name") or "Candidat").strip()
    level = str(cand.get("level") or "").strip()
    cand_track = str(cand.get("track") or "").strip()
    school = str(cand.get("school") or "").strip()

    first_sub = " — ".join(p for p in (level, cand_track) if p)
    sub_lines = [escape_html(p) for p in (first_sub, school) if p]
    sub_html = (
        f'      <p class="sub">\n        {"<br />\n        ".join(sub_lines)}\n      </p>\n'
        if sub_lines
        else ""
    )

    contact_parts: list[str] = []
    home = str(cand.get("home") or "").strip()
    phone = str(cand.get("phone") or "").strip()
    email = str(cand.get("email") or "").strip()
    if home:
        contact_parts.append(escape_html(home))
    if phone:
        contact_parts.append(escape_html(phone))
    if email:
        contact_parts.append(f'<a href="mailto:{escape_html(email)}">{escape_html(email)}</a>')
    for url_key in ("linkedin_url", "github_url", "portfolio_url"):
        raw_url = str(cand.get(url_key) or "").strip()
        if raw_url:
            contact_parts.append(
                f'<a href="{escape_html(raw_url)}">{escape_html(short_url(raw_url))}</a>'
            )

    contact_html = (
        f'      <p class="contact">\n        {" · ".join(contact_parts)}\n      </p>\n'
        if contact_parts
        else ""
    )
    return (
        f"    <header>\n      <h1>{escape_html(name)}</h1>\n{sub_html}{contact_html}    </header>"
    )


def render_availability_box(
    offer: Any,
    cfg: Any,
    tr: Any,
    *,
    is_job: bool,
    is_alt: bool,
    default_start_date: date,
    default_end_date: date,
    default_weeks: int,
) -> str:
    """Render the framed availability, target role, offer reference, and mobility box."""
    if is_job:
        label = "Disponibilité"
        avail = str(
            cfg.job_form_answers.get("Disponibilité")
            or cfg.job_form_answers.get("disponibilité")
            or "Temps partiel (soirs, week-ends) et vacances scolaires"
        ).strip()
    elif is_alt:
        label = "Alternance"
        start = parse_date_safe(cfg.candidate.get("start"), default_start_date)
        avail = str(
            cfg.form_answers.get("Disponibilité")
            or f"Dès {MONTHS_SHORT_FR[start.month - 1]} {start.year}"
        ).strip()
    else:
        label = "Stage"
        start = parse_date_safe(cfg.candidate.get("start"), default_start_date)
        end = parse_date_safe(cfg.candidate.get("end"), default_end_date)
        weeks = int(cfg.candidate.get("weeks") or default_weeks)
        start_s = f"{start.day} {MONTHS_SHORT_FR[start.month - 1]}" + (
            f" {start.year}" if start.year != end.year else ""
        )
        end_s = f"{end.day} {MONTHS_SHORT_FR[end.month - 1]} {end.year}"
        avail = f"{start_s} → {end_s} ({weeks} sem.)"

    mobility = resolve_mobility(cfg, is_job=is_job)
    company = (offer.company or "").strip()
    title = (offer.title or label).strip()
    offer_frag = (
        f" · <strong>Offre :</strong> {escape_html(title[:58])} — {escape_html(company[:30])}"
        if company
        else ""
    )
    return (
        '    <div class="box">\n'
        f"      <strong>{escape_html(label)} :</strong> {escape_html(avail)}"
        f" · <strong>Cible :</strong> {escape_html(tr.targets)}"
        f"{offer_frag}"
        f" · <strong>Mobilité :</strong> {escape_html(mobility)}\n"
        "    </div>"
    )


def offer_owned_keywords(offer: Any, cfg: Any) -> list[str]:
    """Return up to 6 offer keywords that appear in ``cfg.owned_skills``."""
    blob = fold_text(
        " ".join(
            [
                offer.title or "",
                offer.description or "",
                offer.missions or "",
                offer.profile or "",
            ]
        )
    )
    ordered = sorted(
        cfg.owned_skills,
        key=lambda sk: (-cfg.skills_weights.get(sk, 1), sk),
    )
    out: list[str] = []
    for sk in ordered:
        pretty = pretty_skill(sk)
        if keyword_present(blob, sk) and sk not in out:
            out.append(pretty)
        if len(out) >= 6:
            break
    return out


def tag_relevance(tags: Iterable[str], track_key: str, offer_blob_str: str) -> int:
    """Rank an experience or project by track match and offer keyword overlap."""
    folded_tags = [fold_text(t) for t in (tags or ()) if str(t).strip()]
    if not folded_tags:
        return 0
    score = 3 if fold_text(track_key) in folded_tags else 0
    score += sum(1 for t in folded_tags if keyword_present(offer_blob_str, t))
    return score


def render_experiences(
    experiences: Iterable[dict[str, Any]],
    track_key: str,
    offer_blob_str: str,
    *,
    compact: bool,
) -> str:
    """Render candidate professional experiences ordered by relevance."""
    ordered = sorted(
        experiences,
        key=lambda exp: -tag_relevance(exp.get("tags", ()), track_key, offer_blob_str),
    )
    max_items = 3 if compact else 4
    max_bullets = 2 if compact else 4
    chunks: list[str] = ["    <h2>Expériences professionnelles</h2>"]
    for exp in ordered[:max_items]:
        company = str(exp.get("company") or "").strip()
        location = str(exp.get("location") or "").strip()
        dates = str(exp.get("dates") or "").strip()
        role = str(exp.get("role") or "").strip()
        heading = " — ".join(p for p in (company, location) if p) or role
        if not heading:
            continue
        date_html = f'<span class="date">{escape_html(dates)}</span>' if dates else ""
        chunks.append(
            f'    <div class="row">\n      <b>{escape_html(heading)}</b>\n      {date_html}\n    </div>'
        )
        if role and role != heading:
            chunks.append(f'    <div class="role">{escape_html(role)}</div>')
        bullets = [str(b).strip() for b in (exp.get("bullets") or ()) if str(b).strip()][
            :max_bullets
        ]
        if bullets:
            lis = "\n".join(f"      <li>{escape_html(b)}</li>" for b in bullets)
            chunks.append(f"    <ul>\n{lis}\n    </ul>")
    return "\n".join(chunks) if len(chunks) > 1 else ""


def render_projects(
    projects: Iterable[dict[str, Any]],
    track_key: str,
    offer_blob_str: str,
    *,
    compact: bool,
) -> str:
    """Render candidate projects ordered by relevance."""
    ordered = sorted(
        projects,
        key=lambda proj: -tag_relevance(proj.get("tags", ()), track_key, offer_blob_str),
    )
    limit = 3 if compact else 5
    items: list[str] = []
    for proj in ordered[:limit]:
        name = str(proj.get("name") or "").strip()
        summary = str(proj.get("summary") or "").strip()
        url = str(proj.get("url") or "").strip()
        if not name and not summary:
            continue
        parts: list[str] = []
        if name:
            parts.append(f"<strong>{escape_html(name)}</strong>")
        if summary:
            parts.append(f" — {escape_html(summary)}" if name else escape_html(summary))
        if url:
            parts.append(f' (<a href="{escape_html(url)}">{escape_html(short_url(url))}</a>)')
        items.append(f"      <li>{''.join(parts)}</li>")
    if not items:
        return ""
    return "    <h2>Projets</h2>\n    <ul>\n" + "\n".join(items) + "\n    </ul>"


def render_v1_facts(
    facts: Iterable[str],
    tr: Any,
    offer_blob_str: str,
    *,
    compact: bool,
) -> str:
    """Render legacy profile v1 factual bullets filtered and ranked for the offer."""
    cleaned = [str(f).strip() for f in facts if str(f).strip()]
    positive = [f for f in cleaned if not fold_text(f).startswith(GUARDRAIL_FACT_PREFIXES)]
    pool = positive or cleaned
    if not pool:
        return ""
    limit = 5 if compact else 8
    if len(pool) > limit:
        scored = []
        for idx, line in enumerate(pool):
            lf = fold_text(line)
            pts = (2 if idx < 2 else 0) + sum(2 for kw in tr.keywords if keyword_present(lf, kw))
            pts += sum(
                1 for word in lf.split() if len(word) >= 4 and keyword_present(offer_blob_str, word)
            )
            scored.append((pts, idx))
        chosen_idx = {idx for _, idx in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]}
        pool = [line for idx, line in enumerate(pool) if idx in chosen_idx]
    lis = "\n".join(f"      <li>{escape_html(line)}</li>" for line in pool)
    return f"    <h2>Réalisations & Compétences clés</h2>\n    <ul>\n{lis}\n    </ul>"


def filter_skill_block_items(
    raw_items: str,
    owned_folded: set[str],
    known_folded: set[str],
    covered_owned: set[str],
) -> list[str]:
    """Keep only skill block tokens backed by ``owned_folded`` (plus non-skill generic tokens)."""
    tokens = [tok.strip() for tok in raw_items.split("·") if tok.strip()]
    kept_with_skill: list[str] = []
    generic_tokens: list[tuple[int, str]] = []
    result_slots: list[tuple[int, str]] = []

    for idx, tok in enumerate(tokens):
        sub_parts = [p.strip() for p in tok.split(" / ") if p.strip()]
        kept_subs: list[str] = []
        saw_known = False
        for sub in sub_parts:
            sub_f = fold_text(sub)
            matches = [ks for ks in known_folded if keyword_present(sub_f, ks)]
            if matches:
                saw_known = True
                owned_hits = [ks for ks in matches if ks in owned_folded]
                if owned_hits:
                    kept_subs.append(sub)
                    covered_owned.update(owned_hits)
            elif len(sub_parts) == 1:
                generic_tokens.append((idx, tok))
        if kept_subs:
            joined = " / ".join(kept_subs)
            kept_with_skill.append(joined)
            result_slots.append((idx, joined))
        elif not saw_known and len(sub_parts) > 1:
            generic_tokens.append((idx, tok))

    if not kept_with_skill:
        return []
    result_slots.extend(generic_tokens)
    result_slots.sort(key=lambda pair: pair[0])
    return [text for _, text in result_slots]


def render_skills_section(cfg: Any, preset: Any, tr: Any, *, compact: bool) -> str:
    """Render the ATS skills section strictly grounded in ``cfg.owned_skills``."""
    blocks = preset.default_skill_blocks
    order = [k for k in tr.skill_order if k in blocks] or list(blocks.keys())
    owned_folded = {fold_text(s) for s in cfg.owned_skills if str(s).strip()}
    known_folded = {
        fold_text(s)
        for s in (*preset.skills_weights.keys(), *preset.default_owned, *cfg.owned_skills)
        if fold_text(s)
    }
    covered_owned: set[str] = set()
    rendered_lines: list[str] = []
    lang_line = ""

    for key in order:
        raw_title, raw_body = blocks[key]
        title_clean = html.unescape(raw_title)
        body_clean = html.unescape(raw_body)
        if key == "lang":
            custom_lang = str(
                cfg.form_answers.get("Langues") or cfg.form_answers.get("langues") or ""
            ).strip()
            lang_text = custom_lang or body_clean
            lang_line = (
                f'    <p class="skills">\n'
                f"      <strong>{escape_html(title_clean)} :</strong> {escape_html(lang_text)}\n"
                "    </p>"
            )
            continue
        if key == "soft" or not owned_folded:
            rendered_lines.append(
                f'    <p class="skills">\n'
                f"      <strong>{escape_html(title_clean)} :</strong> {escape_html(body_clean)}\n"
                "    </p>"
            )
            continue
        kept = filter_skill_block_items(body_clean, owned_folded, known_folded, covered_owned)
        if kept:
            rendered_lines.append(
                f'    <p class="skills">\n'
                f"      <strong>{escape_html(title_clean)} :</strong> {escape_html(' · '.join(kept))}\n"
                "    </p>"
            )

    extra_owned = [
        s
        for s in sorted(cfg.owned_skills, key=lambda sk: (-cfg.skills_weights.get(sk, 1), sk))
        if fold_text(s) not in covered_owned
        and fold_text(s) not in {"anglais", "francais", "français"}
    ]
    if extra_owned:
        limit = 6 if compact else 10
        extra_str = " · ".join(pretty_skill(s) for s in extra_owned[:limit])
        rendered_lines.append(
            f'    <p class="skills">\n'
            f"      <strong>Compétences complémentaires :</strong> {escape_html(extra_str)}\n"
            "    </p>"
        )
    if lang_line:
        rendered_lines.append(lang_line)

    soft_html = (
        ""
        if compact
        else '\n    <p class="soft"><strong>Qualités :</strong> autonomie · rigueur · documentation claire · travail en équipe · adaptabilité</p>'
    )
    return "    <h2>Compétences</h2>\n" + "\n".join(rendered_lines) + soft_html


def render_education(cfg: Any) -> str:
    """Render the candidate education section."""
    cand = cfg.candidate
    level = str(cand.get("level") or "").strip()
    cand_track = str(cand.get("track") or "").strip()
    school = str(cand.get("school") or "").strip()

    primary = " — ".join(p for p in (level, school) if p) or cand_track or cfg.preset.label
    role_html = (
        f'\n    <div class="role">{escape_html(cand_track)}</div>'
        if cand_track and cand_track != primary
        else ""
    )
    return (
        "    <h2>Formation</h2>\n"
        f'    <div class="row">\n      <b>{escape_html(primary)}</b>\n    </div>{role_html}'
    )

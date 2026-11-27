"""Détection non destructive de doublons d'offres multi-sources (confirmation humaine)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


_LEGAL_SUFFIXES = {
    "sas", "sasu", "sarl", "eurl", "sa", "snc", "sci", "scop", "scic",
    "gie", "association", "asso", "groupe", "france",
}

_STOP_WORDS = {
    "de", "du", "des", "la", "le", "les", "l", "d", "en", "et", "ou",
    "pour", "avec", "sur", "un", "une", "au", "aux", "a",
    "h", "f", "hf", "fh", "cdi", "cdd", "stage", "alternance", "interim",
}


def _ascii_lower(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def normalize_company(name: str) -> str:
    tokens = [t for t in _ascii_lower(name).split() if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def normalize_city(city: str) -> str:
    tokens = [
        t for t in _ascii_lower(city).split()
        if t and not t.isdigit() and t not in {"cedex", "france"}
    ]
    return " ".join(tokens)


_TOKEN_ALIASES = {
    "administrateur": "admin",
    "administratrice": "admin",
    "administration": "admin",
    "technicien": "tech",
    "technicienne": "tech",
    "ingenieure": "ingenieur",
    "reseaux": "reseau",
}


def _stem_token(tok: str) -> str:
    tok = _TOKEN_ALIASES.get(tok, tok)
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith(("ss", "us")):
        tok = tok[:-1]
        tok = _TOKEN_ALIASES.get(tok, tok)
    return tok


def title_tokens(title: str) -> set[str]:
    clean = re.sub(r"\(\s*[hf]\s*/\s*[fh]\s*\)", " ", str(title or ""), flags=re.I)
    return {
        _stem_token(tok)
        for tok in _ascii_lower(clean).split()
        if len(tok) >= 2 and tok not in _STOP_WORDS and not tok.isdigit()
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _cities_compatible(c1: str, c2: str) -> bool:
    if not c1 or not c2:
        return True
    if c1 == c2:
        return True
    return c1 in c2 or c2 in c1


def _to_candidate(row: dict[str, Any], origin: str) -> dict[str, Any] | None:
    comp_raw = str(row.get("company") or "").strip()
    title_raw = str(row.get("title") or "").strip()
    comp_norm = normalize_company(comp_raw)
    toks = title_tokens(title_raw)
    if not comp_norm or not toks:
        return None
    city_raw = str(row.get("city") or "").strip()
    rec_id = str(row.get("id") or row.get("offer_id") or "").strip()
    return {
        "id": rec_id,
        "origin": origin,
        "source": str(row.get("source") or row.get("channel") or origin).strip(),
        "company": comp_raw,
        "company_norm": comp_norm,
        "city": city_raw,
        "city_norm": normalize_city(city_raw),
        "title": title_raw,
        "tokens": toks,
        "status": str(row.get("status") or "").strip(),
        "url": str(row.get("url") or "").strip(),
    }


def find_duplicate_groups(
    offers: list[dict[str, Any]],
    applications: list[dict[str, Any]] | None = None,
    *,
    threshold: float = 0.55,
) -> list[dict[str, Any]]:
    """Regroupe les offres probablement identiques sur plusieurs sources sans rien supprimer."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    seen_offer_ids: set[str] = set()

    for row in offers:
        cand = _to_candidate(row, "offers")
        if cand is None:
            continue
        if cand["id"]:
            seen_offer_ids.add(cand["id"])
        buckets.setdefault(cand["company_norm"], []).append(cand)

    for row in applications or []:
        offer_id = str(row.get("offer_id") or "").strip()
        if offer_id and offer_id in seen_offer_ids:
            continue
        cand = _to_candidate(row, "suivi")
        if cand is None:
            continue
        buckets.setdefault(cand["company_norm"], []).append(cand)

    groups: list[dict[str, Any]] = []
    for _, items in sorted(buckets.items()):
        if len(items) < 2:
            continue
        used = [False] * len(items)
        for i in range(len(items)):
            if used[i]:
                continue
            cluster = [items[i]]
            min_sim = 1.0
            used[i] = True
            for j in range(i + 1, len(items)):
                if used[j]:
                    continue
                if not _cities_compatible(items[i]["city_norm"], items[j]["city_norm"]):
                    continue
                sim = _jaccard(items[i]["tokens"], items[j]["tokens"])
                if sim >= threshold:
                    used[j] = True
                    min_sim = min(min_sim, sim)
                    cluster.append(items[j])
            distinct_records = {
                (m["origin"], m["id"] or f"{m['source']}:{m['title']}:{m['city']}")
                for m in cluster
            }
            if len(distinct_records) < 2:
                continue
            groups.append(
                {
                    "company": cluster[0]["company"],
                    "city": next((m["city"] for m in cluster if m["city"]), ""),
                    "sources": sorted({m["source"] for m in cluster if m["source"]}),
                    "count": len(cluster),
                    "similarity": round(min_sim, 2),
                    "items": [
                        {
                            "id": m["id"],
                            "origin": m["origin"],
                            "source": m["source"],
                            "title": m["title"],
                            "city": m["city"],
                            "status": m["status"],
                            "url": m["url"],
                        }
                        for m in cluster
                    ],
                }
            )
    return groups

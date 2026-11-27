"""Primitive and geographic field validators for candidate profile payloads."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import urlparse

from career_copilot.profile.model import MAX_URL_LEN
from career_copilot.profile.presets_access import get_presets_module

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def is_list_like(value: Any) -> bool:
    return isinstance(value, (list, tuple))


def require_str(
    value: Any,
    field_name: str,
    *,
    max_len: int,
    allow_newlines: bool = False,
) -> str:
    if value is None:
        return ""
    if type(value) is not str:
        raise ValueError(f"Le champ « {field_name} » doit être une chaîne de caractères.")
    text = value.strip()
    if len(text) > max_len:
        raise ValueError(
            f"Le champ « {field_name} » dépasse la taille maximale ({max_len} caractères)."
        )
    if not allow_newlines and _CONTROL_CHAR_RE.search(text):
        raise ValueError(
            f"Le champ « {field_name} » contient des caractères de contrôle interdits."
        )
    if allow_newlines and "\x00" in text:
        raise ValueError(f"Le champ « {field_name} » contient un octet nul interdit.")
    return text


def require_float(
    value: Any,
    field_name: str,
    *,
    min_val: float,
    max_val: float,
) -> float:
    if type(value) is bool:
        raise ValueError(f"Le champ « {field_name} » doit être un nombre valide.")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Le champ « {field_name} » doit être un nombre valide.") from exc
    if not math.isfinite(num) or num < min_val or num > max_val:
        raise ValueError(
            f"Le champ « {field_name} » doit être compris entre {min_val:g} et {max_val:g}."
        )
    return num


def require_int(value: Any, field_name: str, *, min_val: int, max_val: int) -> int:
    if type(value) is bool or type(value) is float:
        raise ValueError(f"Le champ « {field_name} » doit être un entier.")
    try:
        num = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Le champ « {field_name} » doit être un entier.") from exc
    if num < min_val or num > max_val:
        raise ValueError(
            f"Le champ « {field_name} » doit être un entier compris entre {min_val} et {max_val}."
        )
    return num


def validate_https_url(value: Any, field_name: str) -> str:
    text = require_str(value, field_name, max_len=MAX_URL_LEN)
    if not text:
        return ""
    if any(ch.isspace() for ch in text):
        raise ValueError(f"L'URL « {field_name} » ne doit pas contenir d'espaces.")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(
            f"L'URL « {field_name} » doit utiliser le protocole https:// (valeur refusée)."
        )
    host = parsed.hostname or ""
    if not host or "." not in host:
        raise ValueError(f"L'URL « {field_name} » doit contenir un nom de domaine valide.")
    return text


def parse_date_iso(value: Any, field_name: str, *, default: date) -> str:
    if value is None or value == "":
        return default.isoformat()
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Mapping) and "__date__" in value:
        raw_parts = value.get("__date__")
        if (
            not isinstance(raw_parts, (list, tuple))
            or len(raw_parts) != 3
            or any(type(p) is bool for p in raw_parts)
        ):
            raise ValueError(f"Format de date v1 invalide pour « {field_name} ».")
        try:
            return date(int(raw_parts[0]), int(raw_parts[1]), int(raw_parts[2])).isoformat()
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Date invalide pour « {field_name} ».") from exc
    if type(value) is not str:
        raise ValueError(f"La date « {field_name} » doit être au format ISO AAAA-MM-JJ.")
    text = value.strip()
    if not _ISO_DATE_RE.match(text):
        raise ValueError(f"La date « {field_name} » doit respecter le format ISO AAAA-MM-JJ.")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"La date « {field_name} » n'est pas une date calendaire valide.") from exc


def validate_contracts(
    raw_contracts: Any,
    *,
    default_contracts: tuple[str, ...],
) -> list[str]:
    presets_mod = get_presets_module()
    if raw_contracts is None:
        return list(default_contracts)
    if not is_list_like(raw_contracts):
        raise ValueError("Le champ « contracts » doit être une liste de types de contrats.")
    normalized: list[str] = []
    for item in raw_contracts:
        if type(item) is not str:
            raise ValueError("Chaque contrat doit être une chaîne de caractères.")
        token = item.strip().lower()
        if token not in presets_mod.VALID_CONTRACTS:
            allowed = ", ".join(presets_mod.VALID_CONTRACTS)
            raise ValueError(f"Type de contrat inconnu : « {item} » (autorisés : {allowed}).")
        if token not in normalized:
            normalized.append(token)
    if not normalized:
        raise ValueError("Au moins un type de contrat valide doit être sélectionné.")
    return normalized


def validate_zone(item: Any, index: int) -> dict[str, Any]:
    presets_mod = get_presets_module()
    if type(item) is str:
        try:
            return presets_mod.build_zone_from_city(item, km=presets_mod.DEFAULT_RADIUS_KM)
        except KeyError as exc:
            raise ValueError(f"Zone #{index + 1} : ville inconnue « {item} ».") from exc
    if not isinstance(item, Mapping):
        raise ValueError(f"Zone #{index + 1} : format de zone invalide.")
    if ("city" in item or "city_id" in item) and ("lat" not in item and "lon" not in item):
        city_ref = item.get("city_id") or item.get("city")
        km = require_float(
            item.get("km", presets_mod.DEFAULT_RADIUS_KM),
            f"zones[{index}].km",
            min_val=presets_mod.MIN_RADIUS_KM,
            max_val=presets_mod.MAX_RADIUS_KM,
        )
        try:
            zone = presets_mod.build_zone_from_city(str(city_ref), km=km)
        except KeyError as exc:
            raise ValueError(f"Zone #{index + 1} : ville inconnue « {city_ref} ».") from exc
        if item.get("label"):
            zone["label"] = require_str(item["label"], f"zones[{index}].label", max_len=140)
        return zone

    name = require_str(item.get("name"), f"zones[{index}].name", max_len=120)
    if not name:
        raise ValueError(f"Zone #{index + 1} : le nom de la zone est obligatoire.")
    if "lat" not in item or "lon" not in item:
        raise ValueError(f"Zone #{index + 1} : les coordonnées lat et lon sont obligatoires.")
    lat = require_float(item.get("lat"), f"zones[{index}].lat", min_val=-90.0, max_val=90.0)
    lon = require_float(item.get("lon"), f"zones[{index}].lon", min_val=-180.0, max_val=180.0)
    km = require_float(
        item.get("km", presets_mod.DEFAULT_RADIUS_KM),
        f"zones[{index}].km",
        min_val=presets_mod.MIN_RADIUS_KM,
        max_val=presets_mod.MAX_RADIUS_KM,
    )
    department = require_str(item.get("department", ""), f"zones[{index}].department", max_len=10)
    insee = require_str(item.get("insee", ""), f"zones[{index}].insee", max_len=10)
    label = require_str(item.get("label") or name, f"zones[{index}].label", max_len=140) or name
    return {
        "name": name,
        "department": department,
        "insee": insee,
        "lat": lat,
        "lon": lon,
        "km": km,
        "label": label,
    }


def validate_string_list(
    raw_value: Any,
    field_name: str,
    *,
    max_items: int,
    max_item_len: int,
) -> list[str]:
    if raw_value is None:
        return []
    if not is_list_like(raw_value):
        raise ValueError(f"Le champ « {field_name} » doit être une liste de textes.")
    if len(raw_value) > max_items:
        raise ValueError(f"Le champ « {field_name} » dépasse la limite de {max_items} éléments.")
    result: list[str] = []
    for idx, entry in enumerate(raw_value):
        cleaned = require_str(entry, f"{field_name}[{idx}]", max_len=max_item_len)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def validate_string_map(
    raw_value: Any,
    field_name: str,
    *,
    max_items: int,
    max_key_len: int,
    max_val_len: int,
) -> dict[str, str]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, Mapping):
        raise ValueError(f"Le champ « {field_name} » doit être un objet clé/valeur.")
    if len(raw_value) > max_items:
        raise ValueError(f"Le champ « {field_name} » dépasse la limite de {max_items} entrées.")
    out: dict[str, str] = {}
    for k, v in raw_value.items():
        key = require_str(k, f"{field_name}.key", max_len=max_key_len)
        val = require_str(v, f"{field_name}[{key}]", max_len=max_val_len, allow_newlines=True)
        if key and val:
            out[key] = val
    return out

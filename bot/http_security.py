"""Request validation and authentication helpers for Mission Control."""

from __future__ import annotations

import base64
import hmac
import json
from pathlib import Path


def read_json_body(headers, stream, max_bytes: int) -> dict:
    try:
        length = int(headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ValueError("Content-Length invalide") from exc
    if length < 0 or length > max_bytes:
        raise ValueError("Corps de requête trop volumineux")
    if length == 0:
        return {}
    if "application/json" not in headers.get("Content-Type", "").lower():
        raise ValueError("Content-Type application/json requis")
    try:
        data = json.loads(stream.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON invalide") from exc
    if not isinstance(data, dict):
        raise ValueError("Le corps JSON doit être un objet")
    return data


def safe_data_path(path: str | Path, data_dir: Path) -> Path:
    root = data_dir.resolve()
    resolved = Path(path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Chemin de données invalide")
    return resolved


def safe_offer_id(value: object) -> str:
    offer_id = str(value or "")
    if (
        not offer_id
        or offer_id in (".", "..")
        or len(offer_id) > 160
        or "\x00" in offer_id
        or "/" in offer_id
        or "\\" in offer_id
        or Path(offer_id).name != offer_id
    ):
        raise ValueError("Identifiant d'offre invalide")
    return offer_id


def authorized(header: str, token: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        credentials = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = credentials.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(username.encode("utf-8"), b"admin") and hmac.compare_digest(
        password.encode("utf-8"), token.encode("utf-8")
    )

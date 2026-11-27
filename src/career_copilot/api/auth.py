"""Constant-time token authentication for the Career Copilot API."""

from __future__ import annotations

import base64
import hmac
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from career_copilot.fs_privacy import ensure_private_directory

MIN_TOKEN_LENGTH = 32
TOKEN_ENV_VARS = ("CAREER_COPILOT_TOKEN", "MISSION_CONTROL_TOKEN")


@dataclass(frozen=True)
class TokenSettings:
    """Resolved token configuration for API authentication."""

    token: str
    source: str


def load_api_token(
    *,
    explicit_token: str | None = None,
    token_file: Path | None = None,
) -> TokenSettings:
    """Resolve an API token (>= 32 chars) from argument, env, or a 0600 file."""
    if explicit_token is not None:
        cleaned = explicit_token.strip()
        if len(cleaned) < MIN_TOKEN_LENGTH:
            raise RuntimeError(f"Le jeton API doit contenir au moins {MIN_TOKEN_LENGTH} caractères")
        return TokenSettings(token=cleaned, source="explicit")

    for env_name in TOKEN_ENV_VARS:
        configured = os.getenv(env_name, "").strip()
        if configured:
            if len(configured) < MIN_TOKEN_LENGTH:
                raise RuntimeError(
                    f"{env_name} doit contenir au moins {MIN_TOKEN_LENGTH} caractères"
                )
            return TokenSettings(token=configured, source=f"env:{env_name}")

    if token_file is None:
        raise RuntimeError("Aucun jeton API configuré et aucun chemin de fichier fourni")

    target = Path(token_file)
    if target.parent.is_symlink() or target.is_symlink():
        raise RuntimeError("Chemin de jeton API symbolique interdit")
    ensure_private_directory(target.parent)

    if not target.exists():
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))

    if os.name != "nt" and (target.stat().st_mode & 0o077):
        raise RuntimeError(
            f"{target} doit être lisible uniquement par son propriétaire (mode 0600)"
        )
    token = target.read_text(encoding="utf-8").strip()
    if len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(f"{target} doit contenir au moins {MIN_TOKEN_LENGTH} caractères")
    return TokenSettings(token=token, source=f"file:{target.name}")


def verify_auth_header(header: str | None, expected_token: str) -> bool:
    """Verify either `Bearer <token>` or `Basic base64(admin:<token>)` in constant time."""
    if not header or not expected_token:
        return False
    expected_bytes = expected_token.encode("utf-8")
    if header.startswith("Bearer "):
        provided = header[7:].strip().encode("utf-8")
        return hmac.compare_digest(provided, expected_bytes)
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(username.encode("utf-8"), b"admin") and hmac.compare_digest(
            password.encode("utf-8"), expected_bytes
        )
    return False


def _unauthorized_error(http_exception_cls: Any) -> Exception:
    exc: Any = http_exception_cls(
        status_code=401,
        detail="Authentification requise",
        headers={"WWW-Authenticate": 'Bearer realm="career-copilot"'},
    )
    exc.code = "unauthorized"
    return exc


def build_auth_dependency(
    expected_token: str,
    *,
    http_exception_cls: Any,
    header_fn: Callable[..., Any] | None = None,
) -> Callable[..., str]:
    """Create a FastAPI dependency enforcing Bearer/Basic token auth."""
    if header_fn is not None:

        def _require_token(authorization: str | None = header_fn(default=None)) -> str:
            if not verify_auth_header(authorization, expected_token):
                raise _unauthorized_error(http_exception_cls)
            return "authenticated"

        return _require_token

    def _require_token_plain(authorization: str | None = None) -> str:
        if not verify_auth_header(authorization, expected_token):
            raise _unauthorized_error(http_exception_cls)
        return "authenticated"

    return _require_token_plain

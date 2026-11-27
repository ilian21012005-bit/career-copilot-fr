"""Private 0600 profile persistence, partial merge, and thread-safe reload cache."""

from __future__ import annotations

import copy
import json
import logging
import os
import stat
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from career_copilot.fs_privacy import write_private_text
from career_copilot.profile.model import (
    DEFAULT_PROFILE_PATH,
    MAX_PROFILE_BYTES,
    SCHEMA_VERSION,
    CandidateProfileConfig,
    build_config_from_normalized,
    profile_path,
)
from career_copilot.profile.presets_access import get_presets_module
from career_copilot.profile.validation import (
    is_v1_payload,
    migrate_v1_raw_to_v2_input,
    validate_and_normalize_profile_payload,
)

LOG = logging.getLogger("candidate_config")

_LOCK = threading.RLock()
_CACHED_PATH: Path | None = None
_CACHED_CONFIG: CandidateProfileConfig | None = None
_RELOAD_LISTENERS: list[Callable[[CandidateProfileConfig], None]] = []


def default_unconfigured(
    path: Path,
    *,
    load_error: str = "",
) -> CandidateProfileConfig:
    """Build a safe unconfigured fallback config with zero PII."""
    presets_mod = get_presets_module()
    base = validate_and_normalize_profile_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "preset": presets_mod.DEFAULT_PRESET_ID,
            "contracts": ["stage", "job"],
            "zone_preset": presets_mod.DEFAULT_ZONE_PRESET_ID,
        }
    )
    return build_config_from_normalized(
        base,
        path=path,
        configured=False,
        source_version=0,
        load_error=load_error,
    )


def read_private_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    """Read a private JSON file while enforcing no symlink and POSIX mode 0600."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None, "Profil candidat absent."
    except OSError:
        return None, "Profil candidat inaccessible."

    if stat.S_ISLNK(st.st_mode):
        return None, "Lien symbolique interdit pour le profil candidat."
    if not stat.S_ISREG(st.st_mode):
        return None, "Le chemin du profil candidat n'est pas un fichier régulier."
    if os.name != "nt" and (st.st_mode & 0o077):
        return (
            None,
            "Permissions non privées détectées sur le profil candidat (mode 0600 requis).",
        )
    if st.st_size > MAX_PROFILE_BYTES:
        return (
            None,
            "Le fichier de profil candidat dépasse la taille maximale autorisée.",
        )

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "Fichier de profil candidat illisible ou JSON invalide."

    if not isinstance(parsed, dict):
        return None, "Le profil candidat doit contenir un objet JSON."
    return parsed, ""


def write_private_profile_text(target: Path, content: str) -> None:
    """Atomically write profile JSON in mode 0600 with symlink refusal."""
    if target.is_symlink():
        raise ValueError("Lien symbolique interdit pour le profil candidat.")
    write_private_text(target, content)


def merge_partial_payload(
    base: dict[str, Any],
    patch: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge a partial patch cleanly onto an existing normalized v2 payload."""
    incoming: Mapping[str, Any] = (
        migrate_v1_raw_to_v2_input(patch) if is_v1_payload(patch) else patch
    )
    merged = copy.deepcopy(base)

    if "zone_preset" in incoming and "zones" not in incoming:
        merged.pop("zones", None)

    for key, value in incoming.items():
        if key in {"candidate", "preferences"} and isinstance(value, Mapping):
            existing_sub = merged.get(key)
            sub_dict = dict(existing_sub) if isinstance(existing_sub, Mapping) else {}
            sub_dict.update(value)
            merged[key] = sub_dict
        elif key == "skills" and isinstance(value, Mapping):
            existing_skills = merged.get("skills")
            skills_dict = (
                copy.deepcopy(existing_skills) if isinstance(existing_skills, Mapping) else {}
            )
            for sk_key, sk_val in value.items():
                if sk_key == "extra_weights" and isinstance(sk_val, Mapping):
                    existing_w = dict(skills_dict.get("extra_weights") or {})
                    existing_w.update(sk_val)
                    skills_dict["extra_weights"] = existing_w
                else:
                    skills_dict[sk_key] = copy.deepcopy(sk_val)
            merged["skills"] = skills_dict
        else:
            merged[key] = copy.deepcopy(value)

    return merged


def load_profile(
    path: Path | str | None = None,
    *,
    default_path: Path = DEFAULT_PROFILE_PATH,
) -> CandidateProfileConfig:
    """Load and validate candidate profile from disk without mutating global cache."""
    target = profile_path(path, default_path=default_path)
    raw, err = read_private_json(target)
    if raw is None:
        if err != "Profil candidat absent.":
            LOG.warning("Profil candidat existant ignoré : %s", err)
        return default_unconfigured(target, load_error=err)

    source_version = 1 if is_v1_payload(raw) else 2
    try:
        normalized = validate_and_normalize_profile_payload(raw)
    except ValueError as exc:
        LOG.warning("Validation du profil candidat échouée : %s", exc)
        return default_unconfigured(target, load_error=str(exc))

    has_meaningful_data = bool(
        normalized["candidate"].get("name")
        or normalized["candidate"].get("email")
        or normalized["facts"]
        or normalized["form_answers"]
        or source_version == 2
    )
    if not has_meaningful_data:
        LOG.warning("Profil candidat v1 sans données exploitables ; repli sur configured=False.")
    return build_config_from_normalized(
        normalized,
        path=target,
        configured=has_meaningful_data,
        source_version=source_version,
        load_error="",
    )


def register_reload_listener(
    fn: Callable[[CandidateProfileConfig], None],
) -> Callable[[], None]:
    """Register a callback notified on every ``reload_profile`` and return an unregister handle."""
    with _LOCK:
        if fn not in _RELOAD_LISTENERS:
            _RELOAD_LISTENERS.append(fn)

    def _unregister() -> None:
        unregister_reload_listener(fn)

    return _unregister


def unregister_reload_listener(fn: Callable[[CandidateProfileConfig], None]) -> None:
    """Remove a previously registered reload listener."""
    with _LOCK:
        if fn in _RELOAD_LISTENERS:
            _RELOAD_LISTENERS.remove(fn)


def get_profile(
    path: Path | str | None = None,
    *,
    default_path: Path = DEFAULT_PROFILE_PATH,
) -> CandidateProfileConfig:
    """Return the active candidate profile (cached per resolved path, thread-safe)."""
    global _CACHED_PATH, _CACHED_CONFIG
    target = profile_path(path, default_path=default_path).absolute()
    with _LOCK:
        if _CACHED_CONFIG is not None and target == _CACHED_PATH:
            return _CACHED_CONFIG
        cfg = load_profile(target, default_path=default_path)
        _CACHED_PATH = target
        _CACHED_CONFIG = cfg
        return cfg


def reload_profile(
    path: Path | str | None = None,
    *,
    default_path: Path = DEFAULT_PROFILE_PATH,
) -> CandidateProfileConfig:
    """Reload profile from disk, refresh cache, and notify listeners."""
    global _CACHED_PATH, _CACHED_CONFIG
    target = profile_path(path, default_path=default_path).absolute()
    with _LOCK:
        cfg = load_profile(target, default_path=default_path)
        _CACHED_PATH = target
        _CACHED_CONFIG = cfg
        listeners = tuple(_RELOAD_LISTENERS)
    for listener in listeners:
        listener(cfg)
    return cfg


def save_profile_payload(
    raw: dict[str, Any],
    path: Path | str | None = None,
    *,
    default_path: Path = DEFAULT_PROFILE_PATH,
) -> CandidateProfileConfig:
    """Validate, merge if partial, atomically write in mode 0600, and reload cache."""
    if not isinstance(raw, Mapping):
        raise ValueError("Le profil candidat doit être un objet JSON.")

    target = profile_path(path, default_path=default_path)
    with _LOCK:
        candidate_payload: Mapping[str, Any] = raw
        existing_raw, existing_err = read_private_json(target)
        if existing_raw is not None and not existing_err:
            try:
                existing_normalized = validate_and_normalize_profile_payload(existing_raw)
            except ValueError:
                existing_normalized = None
            if existing_normalized is not None:
                candidate_payload = merge_partial_payload(existing_normalized, raw)

        normalized = validate_and_normalize_profile_payload(dict(candidate_payload))
        serialized = json.dumps(normalized, ensure_ascii=False, indent=2) + "\n"
        write_private_profile_text(target, serialized)

    return reload_profile(target, default_path=default_path)

"""Backward-compatible re-export shim for ``career_copilot.profile``.

All profile modeling, v1->v2 validation, and private 0600 storage now live in
``src/career_copilot/profile/``. This thin shim preserves legacy imports from
``Job-Etudiant/bot/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BOT_DIR = Path(__file__).resolve().parent
_SRC_DIR = BOT_DIR.parent / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.profile import (  # noqa: E402
    DEFAULT_END_DATE,
    DEFAULT_JOB_RADIUS_KM,
    DEFAULT_START_DATE,
    DEFAULT_WEEKS,
    LOG,
    MAX_CUSTOM_EXCLUDES,
    MAX_CUSTOM_QUERIES,
    MAX_CUSTOM_TITLES,
    MAX_EXTRA_WEIGHTS,
    MAX_FACT_LEN,
    MAX_FACTS,
    MAX_FORM_ANSWERS,
    MAX_FORM_KEY_LEN,
    MAX_FORM_VAL_LEN,
    MAX_OWNED_SKILLS,
    MAX_PROFILE_BYTES,
    MAX_SKILL_LEN,
    MAX_URL_LEN,
    MAX_ZONES,
    PROFILE_PATH_ENV,
    SCHEMA_VERSION,
    STANDALONE_ENV,
    CandidateProfileConfig,
    build_example_profile_v2,
    compute_contract_exclusions,
    register_reload_listener,
    unregister_reload_listener,
    validate_and_normalize_profile_payload,
)
from career_copilot.profile import (
    is_standalone_mode as _profile_is_standalone_mode,
)
from career_copilot.profile import (
    build_config_from_normalized as _build_config_from_normalized,
)
from career_copilot.profile import (
    default_unconfigured as _default_unconfigured,
)
from career_copilot.profile import (
    get_profile as _get_profile,
)
from career_copilot.profile import (
    is_v1_payload as _is_v1_payload,
)
from career_copilot.profile import (
    load_profile as _load_profile,
)
from career_copilot.profile import (
    merge_partial_payload as _merge_partial_payload,
)
from career_copilot.profile import (
    migrate_v1_raw_to_v2_input as _migrate_v1_raw_to_v2_input,
)
from career_copilot.profile import (
    profile_path as _profile_path,
)
from career_copilot.profile import (
    read_private_json as _read_private_json,
)
from career_copilot.profile import (
    reload_profile as _reload_profile,
)
from career_copilot.profile import (
    save_profile_payload as _save_profile_payload,
)
from career_copilot.profile import (
    write_private_profile_text as _write_private_profile_text,
)

DEFAULT_PROFILE_PATH = BOT_DIR / "data" / "candidate-profile.json"


def is_standalone_mode(project_root: Path | str | None = None) -> bool:
    return _profile_is_standalone_mode(project_root)


def profile_path(path: Path | str | None = None) -> Path:
    return _profile_path(path, default_path=DEFAULT_PROFILE_PATH)


def load_profile(path: Path | str | None = None) -> CandidateProfileConfig:
    return _load_profile(path, default_path=DEFAULT_PROFILE_PATH)


def get_profile(path: Path | str | None = None) -> CandidateProfileConfig:
    return _get_profile(path, default_path=DEFAULT_PROFILE_PATH)


def reload_profile(path: Path | str | None = None) -> CandidateProfileConfig:
    return _reload_profile(path, default_path=DEFAULT_PROFILE_PATH)


def save_profile_payload(
    raw: dict[str, Any],
    path: Path | str | None = None,
) -> CandidateProfileConfig:
    return _save_profile_payload(raw, path, default_path=DEFAULT_PROFILE_PATH)


__all__ = [
    "BOT_DIR",
    "DEFAULT_END_DATE",
    "DEFAULT_JOB_RADIUS_KM",
    "DEFAULT_PROFILE_PATH",
    "DEFAULT_START_DATE",
    "DEFAULT_WEEKS",
    "LOG",
    "MAX_CUSTOM_EXCLUDES",
    "MAX_CUSTOM_QUERIES",
    "MAX_CUSTOM_TITLES",
    "MAX_EXTRA_WEIGHTS",
    "MAX_FACTS",
    "MAX_FACT_LEN",
    "MAX_FORM_ANSWERS",
    "MAX_FORM_KEY_LEN",
    "MAX_FORM_VAL_LEN",
    "MAX_OWNED_SKILLS",
    "MAX_PROFILE_BYTES",
    "MAX_SKILL_LEN",
    "MAX_URL_LEN",
    "MAX_ZONES",
    "PROFILE_PATH_ENV",
    "SCHEMA_VERSION",
    "STANDALONE_ENV",
    "CandidateProfileConfig",
    "_build_config_from_normalized",
    "_default_unconfigured",
    "_is_v1_payload",
    "_merge_partial_payload",
    "_migrate_v1_raw_to_v2_input",
    "_read_private_json",
    "_write_private_profile_text",
    "build_example_profile_v2",
    "compute_contract_exclusions",
    "get_profile",
    "is_standalone_mode",
    "load_profile",
    "profile_path",
    "register_reload_listener",
    "reload_profile",
    "save_profile_payload",
    "unregister_reload_listener",
    "validate_and_normalize_profile_payload",
]

"""Backward-compatible re-export shim for ``career_copilot.scoring``.

All scoring rules, student-job heuristics, and engine logic now live in
``src/career_copilot/scoring/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.scoring import (
    BAC3_ACCEPTED,
    DEVELOPMENT_ROLE_MARKERS,
    LEVEL_MARKERS,
    MAX_POINTS,
    OFF_TARGET_HARD,
    OFF_TARGET_SOFT,
    OPERATIONAL_KEEP,
    TARGET_KEYWORDS,
    Score,
    campaign_of,
    evaluate,
    is_eligible_for_plan,
    summary,
)
from career_copilot.scoring import (
    JOB_SKILL_GROUPS as _JOB_SKILL_GROUPS,
)
from career_copilot.scoring import (
    accepts_bac3 as _accepts_bac3,
)
from career_copilot.scoring import (
    apply_fit_caps as _apply_fit_caps,
)
from career_copilot.scoring import (
    candidate_level_rank as _candidate_level_rank,
)
from career_copilot.scoring import (
    deep_fit_flags as _deep_fit_flags,
)
from career_copilot.scoring import (
    duration_verdict as _duration_verdict,
)
from career_copilot.scoring import (
    evaluate_student_job as _evaluate_student_job,
)
from career_copilot.scoring import (
    evaluate_student_job_contract as _evaluate_student_job_contract,
)
from career_copilot.scoring import (
    evaluate_student_job_location as _evaluate_student_job_location,
)
from career_copilot.scoring import (
    exclusive_bac5_inge as _exclusive_bac5_inge,
)
from career_copilot.scoring import (
    mission_reject as _mission_reject,
)
from career_copilot.scoring import (
    off_target_hard as _off_target_hard,
)
from career_copilot.scoring import (
    parse_duration_range as _parse_duration_range,
)
from career_copilot.scoring import (
    parse_duration_weeks as _parse_duration_weeks,
)
from career_copilot.scoring import (
    score_contract as _contrat,
)
from career_copilot.scoring import (
    score_freshness as _fraicheur,
)
from career_copilot.scoring import (
    score_level as _niveau,
)
from career_copilot.scoring import (
    score_location as _lieu,
)
from career_copilot.scoring import (
    score_skills as _competences,
)
from career_copilot.scoring import (
    stage_schedule_notes as _stage_schedule_notes,
)

__all__ = [
    "BAC3_ACCEPTED",
    "DEVELOPMENT_ROLE_MARKERS",
    "LEVEL_MARKERS",
    "MAX_POINTS",
    "OFF_TARGET_HARD",
    "OFF_TARGET_SOFT",
    "OPERATIONAL_KEEP",
    "TARGET_KEYWORDS",
    "Score",
    "_JOB_SKILL_GROUPS",
    "_accepts_bac3",
    "_apply_fit_caps",
    "_candidate_level_rank",
    "_competences",
    "_contrat",
    "_deep_fit_flags",
    "_duration_verdict",
    "_evaluate_student_job",
    "_evaluate_student_job_contract",
    "_evaluate_student_job_location",
    "_exclusive_bac5_inge",
    "_fraicheur",
    "_lieu",
    "_mission_reject",
    "_niveau",
    "_off_target_hard",
    "_parse_duration_range",
    "_parse_duration_weeks",
    "_stage_schedule_notes",
    "campaign_of",
    "evaluate",
    "is_eligible_for_plan",
    "summary",
]

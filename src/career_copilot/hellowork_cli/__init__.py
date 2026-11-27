"""Modular HelloWork CLI command dispatcher and subcommand modules."""

from __future__ import annotations

from collections.abc import Sequence

from . import apply_flow, commands_core, commands_extra, reconcile
from .deps import (
    AUTO_SUBMIT_CAPABILITY,
    BLOCKING_ERROR_PREFIXES,
    CliDeps,
    alert_hw_session_once,
    find_offer,
    has_auto_submit_capability,
    has_blocking_errors,
    json_dict,
    json_list,
    short,
    stage_cv_is_valid,
    stats_line,
    urls_from_file,
    utf8_console,
)
from .parser import build_parser


def dispatch(deps: CliDeps, argv: Sequence[str] | None = None) -> int:
    utf8_console()
    parser = build_parser(deps)
    args = parser.parse_args(list(argv) if argv is not None else None)
    deps.store.init()
    command = args.command or "list"
    handlers = {
        "init": commands_core.cmd_init,
        "add": commands_core.cmd_add,
        "list": commands_core.cmd_list,
        "show": commands_core.cmd_show,
        "prepare": commands_core.cmd_prepare,
        "refresh": commands_core.cmd_refresh,
        "plan": commands_core.cmd_plan,
        "daily": reconcile.cmd_daily,
        "apply": reconcile.cmd_apply,
        "confirm": commands_core.cmd_confirm,
        "skip": commands_core.cmd_skip,
        "mark": commands_core.cmd_mark,
        "open": commands_core.cmd_open,
        "sync": commands_core.cmd_sync,
        "report": commands_core.cmd_report,
        "stats": commands_core.cmd_stats,
        "partner-deep": commands_extra.cmd_partner_deep,
        "lm-queue": commands_extra.cmd_lm_queue,
        "lm-write": commands_extra.cmd_lm_write,
        "lm-run": commands_extra.cmd_lm_run,
        "ready-queue": commands_extra.cmd_ready_queue,
        "ats-check": commands_extra.cmd_ats_check,
        "jobspy": commands_extra.cmd_jobspy,
        "manual-queue": commands_extra.cmd_manual_queue,
    }
    return handlers[command](deps, args)


__all__ = [
    "AUTO_SUBMIT_CAPABILITY",
    "BLOCKING_ERROR_PREFIXES",
    "CliDeps",
    "alert_hw_session_once",
    "apply_flow",
    "build_parser",
    "commands_core",
    "commands_extra",
    "dispatch",
    "find_offer",
    "has_auto_submit_capability",
    "has_blocking_errors",
    "json_dict",
    "json_list",
    "reconcile",
    "short",
    "stage_cv_is_valid",
    "stats_line",
    "urls_from_file",
    "utf8_console",
]

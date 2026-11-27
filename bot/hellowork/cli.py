"""Backward-compatible re-export shim for ``career_copilot.hellowork_cli``.

All HelloWork CLI argument parsing, command handlers, reconciliation, and
Playwright apply orchestration now live in ``src/career_copilot/hellowork_cli/``.
"""

# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import offer_letters
import suivi
from config import DATA_DIR, load_env

from . import (
    alerts,
    ats_alive,
    daily,
    geo,
    jobspy_source,
    kit,
    lm_ai,
    partner_deep,
    profile,
    ready_queue,
    report,
    store,
    submit_handler,
)
from . import offer as offers
from . import score as scoring

_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if _SRC_DIR.is_dir() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from career_copilot.hellowork_cli import (
    AUTO_SUBMIT_CAPABILITY,
    BLOCKING_ERROR_PREFIXES,
    CliDeps,
)
from career_copilot.hellowork_cli import (
    apply_flow as _apply_flow,
)
from career_copilot.hellowork_cli import (
    build_parser as _build_parser,
)
from career_copilot.hellowork_cli import (
    commands_core as _core,
)
from career_copilot.hellowork_cli import (
    commands_extra as _extra,
)
from career_copilot.hellowork_cli import (
    dispatch as _dispatch,
)
from career_copilot.hellowork_cli import (
    has_auto_submit_capability as _has_auto_submit_capability,
)
from career_copilot.hellowork_cli import (
    has_blocking_errors as _has_blocking_errors,
)
from career_copilot.hellowork_cli import (
    json_dict as _json_dict,
)
from career_copilot.hellowork_cli import (
    json_list as _json_list,
)
from career_copilot.hellowork_cli import (
    reconcile as _reconcile,
)
from career_copilot.hellowork_cli import (
    short as _short,
)
from career_copilot.hellowork_cli import (
    stage_cv_is_valid as _stage_cv_is_valid,
)
from career_copilot.hellowork_cli import (
    urls_from_file as _urls_from_file,
)
from career_copilot.hellowork_cli import (
    utf8_console as _utf8_console,
)
from career_copilot.hellowork_cli.deps import (
    alert_hw_session_once as _alert_hw_session_once_impl,
)
from career_copilot.hellowork_cli.deps import (
    find_offer as _find_offer_impl,
)
from career_copilot.hellowork_cli.deps import (
    stats_line as _stats_line_impl,
)


def _deps() -> CliDeps:
    return CliDeps(
        store=store,
        daily=daily,
        report=report,
        offers=offers,
        scoring=scoring,
        geo=geo,
        kit=kit,
        profile=profile,
        alerts=alerts,
        offer_letters=offer_letters,
        suivi=suivi,
        submit_handler=submit_handler,
        partner_deep=partner_deep,
        lm_ai=lm_ai,
        ready_queue=ready_queue,
        ats_alive=ats_alive,
        jobspy_source=jobspy_source,
        load_env=load_env,
        data_dir=lambda: DATA_DIR,
        stats_line_fn=_stats_line,
        apply_rows_fn=_apply_rows,
        offer_from_row_fn=_offer_from_row,
        stage_cv_is_valid_fn=_stage_cv_is_valid,
        alert_hw_session_once_fn=_alert_hw_session_once,
        reconcile_pending_fn=_reconcile_pending_hellowork,
        reconcile_excel_fn=_reconcile_excel_projections,
    )


def main(argv: list[str] | None = None) -> int:
    return _dispatch(_deps(), argv)


def _parser():
    return _build_parser(_deps())


def _alert_hw_session_once(status: str, detail: str) -> None:
    _alert_hw_session_once_impl(_deps(), status, detail)


def _find(offer_id: str) -> Any:
    return _find_offer_impl(_deps(), offer_id)


def _stats_line() -> str:
    return _stats_line_impl(_deps())


def _offer_from_row(row: Any) -> offers.Offer:
    return offers.from_row(row)


def _reconcile_excel_projections(log: Any) -> bool:
    return _reconcile.reconcile_excel_projections(_deps(), log)


def _reconcile_pending_hellowork(context: Any, log: Any) -> int:
    return _reconcile.reconcile_pending_hellowork(_deps(), context, log)


def _apply_rows(rows: Any, **kwargs: Any) -> bool:
    return _apply_flow.apply_rows(_deps(), rows, **kwargs)


def _init(args: Any) -> int:
    return _core.cmd_init(_deps(), args)


def _add(args: Any) -> int:
    return _core.cmd_add(_deps(), args)


def _list(args: Any) -> int:
    return _core.cmd_list(_deps(), args)


def _show(args: Any) -> int:
    return _core.cmd_show(_deps(), args)


def _prepare(args: Any) -> int:
    return _core.cmd_prepare(_deps(), args)


def _refresh(args: Any) -> int:
    return _core.cmd_refresh(_deps(), args)


def _mark(args: Any) -> int:
    return _core.cmd_mark(_deps(), args)


def _plan(args: Any) -> int:
    return _core.cmd_plan(_deps(), args)


def _daily(args: Any) -> int:
    return _reconcile.cmd_daily(_deps(), args)


def _apply(args: Any) -> int:
    return _reconcile.cmd_apply(_deps(), args)


def _confirm(args: Any) -> int:
    return _core.cmd_confirm(_deps(), args)


def _skip(args: Any) -> int:
    return _core.cmd_skip(_deps(), args)


def _open(args: Any) -> int:
    return _core.cmd_open(_deps(), args)


def _sync(args: Any) -> int:
    return _core.cmd_sync(_deps(), args)


def _report(args: Any) -> int:
    return _core.cmd_report(_deps(), args)


def _stats(args: Any) -> int:
    return _core.cmd_stats(_deps(), args)


def _ready_queue(args: Any) -> int:
    return _extra.cmd_ready_queue(_deps(), args)


def _ats_check(args: Any) -> int:
    return _extra.cmd_ats_check(_deps(), args)


def _lm_queue(args: Any) -> int:
    return _extra.cmd_lm_queue(_deps(), args)


def _lm_write(args: Any) -> int:
    return _extra.cmd_lm_write(_deps(), args)


def _lm_run(args: Any) -> int:
    return _extra.cmd_lm_run(_deps(), args)


def _partner_deep(args: Any) -> int:
    return _extra.cmd_partner_deep(_deps(), args)


def _jobspy(args: Any) -> int:
    return _extra.cmd_jobspy(_deps(), args)


def _manual_queue(args: Any) -> int:
    return _extra.cmd_manual_queue(_deps(), args)


__all__ = [
    "AUTO_SUBMIT_CAPABILITY",
    "BLOCKING_ERROR_PREFIXES",
    "DATA_DIR",
    "_apply_rows",
    "_daily",
    "_has_auto_submit_capability",
    "_has_blocking_errors",
    "_json_dict",
    "_json_list",
    "_offer_from_row",
    "_reconcile_excel_projections",
    "_reconcile_pending_hellowork",
    "_short",
    "_stage_cv_is_valid",
    "_stats_line",
    "_urls_from_file",
    "_utf8_console",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())

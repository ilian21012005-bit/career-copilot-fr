"""Secondary HelloWork CLI commands (queues, ATS probe, LM tools, partner deep, JobSpy)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from career_copilot.hellowork_cli.deps import CliDeps


def cmd_ready_queue(deps: CliDeps, args: Any) -> int:
    rows = deps.ready_queue.ready(limit=args.limit)
    path = deps.ready_queue.export_json(limit=args.limit)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"{len(rows)} pret(s) a cliquer -> {path}", flush=True)
    return 0


def cmd_ats_check(deps: CliDeps, args: Any) -> int:
    print(json.dumps(deps.ats_alive.check(args.url), ensure_ascii=False, indent=2))
    return 0


def cmd_lm_queue(deps: CliDeps, args: Any) -> int:
    rows = deps.lm_ai.pending(limit=args.limit, min_score=args.min_score)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"{len(rows)} offre(s) sans lettre IA", flush=True)
    return 0


def cmd_lm_write(deps: CliDeps, args: Any) -> int:
    body = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    res = deps.lm_ai.write_ai_letter(args.id, body)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


def cmd_lm_run(deps: CliDeps, args: Any) -> int:
    if args.force:
        os.environ["LM_FORCE"] = "1"
    reports = deps.lm_ai.process_pending_local(limit=args.limit)
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    ok = sum(1 for r in reports if r.get("ok"))
    print(f"{ok}/{len(reports)} lettres IA", flush=True)
    return 0 if ok == len(reports) else 1


def cmd_partner_deep(deps: CliDeps, args: Any) -> int:
    reports = deps.partner_deep.enrich_pending(
        limit=getattr(args, "limit", 20) or 20,
        force=bool(getattr(args, "force", False)),
    )
    print(f"{len(reports)} offre(s) analysée(s)")
    for r in reports:
        if r.get("error"):
            print(f"  ERR {r.get('id')}: {r['error']}")
            continue
        if r.get("skipped"):
            print(f"  skip {r.get('id')} ({r.get('reason')})")
            continue
        flag = "AUTO" if r.get("auto_submit") else ("MANUEL" if r.get("manual_required") else "—")
        rej = f" | REJET {r.get('reject_reason')}" if r.get("rejected") else ""
        print(
            f"  [{flag}] {r.get('score')}/100 {r.get('company')} — "
            f"{str(r.get('title') or '')[:50]} | {r.get('apply_capability')} | {r.get('method')}{rej}"
        )
    manual = deps.partner_deep.manual_queue()
    print(f"\nFile manuelle ({len(manual)}) — à candidater toi-même :")
    for row in manual[:15]:
        print(f"  - {row['company']} | {str(row['title'])[:60]}")
        print(f"    {row['url']}")
        if row.get("partner_url"):
            print(f"    partenaire: {row['partner_url']}")
    return 0


def cmd_jobspy(deps: CliDeps, args: Any) -> int:
    if not deps.jobspy_source.available():
        print("python-jobspy absent — pip install python-jobspy")
        return 1
    summary = deps.jobspy_source.scrape_batch(
        dry_run=bool(getattr(args, "dry_run", False)),
        results_wanted=int(getattr(args, "results", 10) or 10),
    )
    print(
        f"JobSpy ok={summary.get('ok')} unique={summary.get('unique_stage_like')} "
        f"added={summary.get('added')} rejected={summary.get('rejected')}"
    )
    for sample in (summary.get("samples") or [])[:12]:
        print(
            f"  - {sample.get('company')} | {str(sample.get('title') or '')[:55]} "
            f"| score={sample.get('score')} | {sample.get('mode')}"
        )
    if summary.get("errors"):
        print("errors:", summary["errors"][:5])
    if summary.get("ok") and not summary.get("dry_run"):
        deep = deps.partner_deep.enrich_pending(limit=15)
        print(f"partner_deep: {len(deep)} offres")
    return 0 if summary.get("ok") else 1


def cmd_manual_queue(deps: CliDeps, args: Any) -> int:
    _ = args
    rows = deps.partner_deep.manual_queue()
    autos = deps.partner_deep.auto_queue()
    print(f"AUTO HelloWork possibles : {len(autos)}")
    for row in autos[:10]:
        print(f"  [AUTO] {row['score']} {row['company']} — {str(row['title'])[:55]}")
    print(f"\nMANUEL (site partenaire / autre) : {len(rows)}")
    for row in rows:
        print(f"  [MANUEL] {row['score']} {row['company']} — {str(row['title'])[:55]}")
        print(f"    {row['url']}")
        if row.get("partner_url"):
            print(f"    partenaire: {row['partner_url']}")
    print(
        "\nRappel : l'auto-submit Playwright ne part que via `python -m hellowork apply` (jamais silencieux)."
    )
    return 0

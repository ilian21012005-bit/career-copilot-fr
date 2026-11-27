"""Lecture agrégée, sans écriture, de l'état du funnel HelloWork."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

from . import store


def snapshot(db_path: Path | None = None, *, today: date | None = None) -> dict[str, Any]:
    """Retourne des compteurs sans exposer noms, titres, URL ni identifiants."""
    source_path = db_path or store.DB_PATH
    if source_path.is_symlink() or source_path.parent.is_symlink():
        raise ValueError("Base HelloWork symbolique interdite")
    path = source_path.resolve(strict=True)
    uri = f"{path.as_uri()}?mode=ro"
    current_day = (today or date.today()).isoformat()
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        required = {"applications", "offers", "plan", "mails"}
        missing = required - tables
        if missing:
            raise RuntimeError(f"Schéma carrière incomplet: {', '.join(sorted(missing))}")

        def grouped(sql: str) -> dict[str, int]:
            return {str(row[0] or "<vide>"): int(row[1]) for row in conn.execute(sql)}

        return {
            "date": current_day,
            "applications_by_status": grouped(
                "SELECT status, count(*) FROM applications GROUP BY status"
            ),
            "applications_by_status_channel": {
                f"{row[0]}/{row[1]}/{row[2]}": int(row[3])
                for row in conn.execute(
                    "SELECT status, coalesce(channel, '<vide>'), "
                    "CASE WHEN coalesce(external_id, '') = '' THEN 'sans_id' ELSE 'avec_id' END, "
                    "count(*) FROM applications GROUP BY 1, 2, 3"
                )
            },
            "application_mail_evidence": {
                f"{row[0]}/{row[1]}": int(row[2])
                for row in conn.execute(
                    "SELECT a.status, m.kind, count(*) FROM applications a "
                    "JOIN mails m ON m.message_id = a.external_id "
                    "GROUP BY a.status, m.kind"
                )
            },
            "sent_without_applied_mail_by_channel": grouped(
                "SELECT coalesce(a.channel, '<vide>'), count(*) FROM applications a "
                "WHERE a.status = 'sent' AND NOT EXISTS ("
                "SELECT 1 FROM mails m WHERE m.message_id = a.external_id "
                "AND m.kind = 'applied') GROUP BY a.channel"
            ),
            "offers_by_status": grouped(
                "SELECT status, count(*) FROM offers GROUP BY status"
            ),
            "capability_by_status": {
                f"{row[0]}/{row[1]}": int(row[2])
                for row in conn.execute(
                    "SELECT status, coalesce(apply_capability, '<vide>'), count(*) "
                    "FROM offers GROUP BY status, apply_capability"
                )
            },
            "mail_events_by_kind": grouped(
                "SELECT kind, count(*) FROM mails GROUP BY kind"
            ),
            "plan_today_by_status": {
                str(row[0] or "<vide>"): int(row[1])
                for row in conn.execute(
                    "SELECT status, count(*) FROM plan WHERE day = ? GROUP BY status",
                    (current_day,),
                )
            },
            "stale_planned_rows": int(
                conn.execute(
                    "SELECT count(*) FROM plan p JOIN offers o ON o.id = p.offer_id "
                    "WHERE p.status = 'planned' AND o.status IN ('applied', 'ignored')"
                ).fetchone()[0]
            ),
            "last_offer_seen": conn.execute("SELECT max(last_seen) FROM offers").fetchone()[0],
        }


def pending_reconciliations(db_path: Path | None = None) -> dict[str, int]:
    """Retourne les compteurs d'actions en attente de rapprochement humain."""
    source_path = db_path or store.DB_PATH
    if source_path.is_symlink() or source_path.parent.is_symlink():
        raise ValueError("Base HelloWork symbolique interdite")
    path = source_path.resolve(strict=True)
    uri = f"{path.as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        def count_one(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "to_finish": count_one("SELECT count(*) FROM offers WHERE status = 'to_finish'"),
            "submission_unknown": count_one("SELECT count(*) FROM offers WHERE status = 'submission_unknown'"),
            "submission_pending": count_one("SELECT count(*) FROM offers WHERE status = 'submission_pending'"),
            "applications_pending": count_one(
                "SELECT count(*) FROM applications "
                "WHERE status IN ('to_finish', 'submission_unknown', 'submission_pending')"
            ),
            "stale_planned_rows": count_one(
                "SELECT count(*) FROM plan p JOIN offers o ON o.id = p.offer_id "
                "WHERE p.status = 'planned' AND o.status IN ('applied', 'ignored')"
            ),
        }


def main() -> None:
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

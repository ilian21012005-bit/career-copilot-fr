"""Exports for the application ledger."""

from __future__ import annotations

import csv
import io
import json


def applications_csv(_get_candidatures_data, _application_proof_state) -> bytes:
    """Export the candidature ledger without exposing local filesystem paths."""
    applications = (_get_candidatures_data() or {}).get("applications", [])
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    def safe_cell(value):
        text = str(value or "")
        # Prevent spreadsheet formula execution on CSV open.
        if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + text
        return text
    writer.writerow([
        "id", "offer_id", "company", "title", "applied_at", "channel",
        "status", "proof_state", "evidence", "external_id",
    ])
    for application in applications:
        proof_state = _application_proof_state(application)
        writer.writerow([
            safe_cell(application.get("id", "")),
            safe_cell(application.get("offer_id", "")),
            safe_cell(application.get("company", "")),
            safe_cell(application.get("title", "")),
            safe_cell(application.get("applied_at", "")),
            safe_cell(application.get("channel", "")),
            safe_cell(application.get("status", "")),
            safe_cell(proof_state),
            safe_cell(application.get("evidence", "")),
            safe_cell(application.get("external_id", "")),
        ])
    return output.getvalue().encode("utf-8-sig")


def applications_json(get_data, proof_state, now) -> bytes:
    applications = (get_data() or {}).get("applications", [])
    return json.dumps({
        "exported_at": now().astimezone().isoformat(timespec="seconds"),
        "applications": [{**item, "proof_state": proof_state(item)} for item in applications],
    }, ensure_ascii=False, indent=2).encode("utf-8")

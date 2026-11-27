"""Read operational reports and classify application evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _application_proof_state(application: dict) -> str:
    """Classify delivery conservatively; a manual note is not external proof."""
    status = str(application.get("status") or "").lower()
    channel = str(application.get("channel") or "").lower()
    evidence = str(application.get("evidence") or "").lower()
    if status == "replied":
        return "replied"
    if status == "withdrawn":
        return "withdrawn"
    if status in ("submission_unknown", "submission_pending", "to_finish"):
        return "submission_unknown"
    proof_kind = application.get("proof_kind")
    if application.get("proof_reference"):
        if proof_kind in ("authenticated_receipt", "ats_receipt"):
            return "submitted_with_evidence"
        if proof_kind == "smtp_accepted":
            return "smtp_accepted"
    if "manuel" in channel or "manual" in channel or "telegram" in channel:
        return "declared_applied"
    if "confirmation externe vérifiée" in evidence:
        return "submitted_with_evidence"
    if status == "applied":
        return "declared_applied"
    return "submission_unknown"


def _read_operations_report(filename: str, PROJECT_ROOT) -> dict:
    path = PROJECT_ROOT / "Job-Etudiant" / "bot" / "data" / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"available": False, "checked_at": None, "issues": [], "summary": {}}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"available": False, "error": str(exc), "issues": [], "summary": {}}


def _get_backup_report(PROJECT_ROOT) -> dict:
    from runtime_hooks import backup_directory

    root = backup_directory(PROJECT_ROOT)
    status = {}
    try:
        observed = json.loads(
            (PROJECT_ROOT / "data" / "backup-status.json").read_text(encoding="utf-8")
        )
        published_root = Path(observed["backup_root"])
        if not published_root.is_absolute():
            raise ValueError("Destination de sauvegarde relative")
        root = published_root
        status = observed
    except (OSError, ValueError, TypeError, KeyError):
        pass
    backups = []
    invalid = 0
    try:
        directories = sorted(root.iterdir(), reverse=True)
    except OSError:
        directories = []
    for directory in directories:
        if directory.is_symlink() or not directory.is_dir():
            continue
        manifest = directory / "manifest.json"
        if manifest.is_symlink():
            invalid += 1
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            files = data["files"]
            if not isinstance(files, list) or any(
                not isinstance(item, dict) for item in files
            ):
                raise ValueError("Manifeste invalide")
            backups.append(
                {
                    "name": directory.name,
                    "created_at": data.get("created_at"),
                    "files": len(files),
                    "size": sum(int(item.get("size", 0)) for item in files),
                }
            )
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError, TypeError, ValueError, KeyError):
            invalid += 1
    backups.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    last = backups[0] if backups else None
    status_summary = {
        "checked_at": status.get("checked_at"),
        "snapshot": status.get("snapshot"),
        "verified": None,
        "independent": status.get("independent", "unknown"),
        "error": status.get("error"),
    }
    if status.get("verified") is False:
        status_summary["verified"] = False
    elif status.get("verified") is True:
        snapshot = next(
            (item for item in backups if item["name"] == status.get("snapshot")), None
        )
        if snapshot is not None:
            try:
                import sys as _sys

                _ops_daemons = Path(PROJECT_ROOT) / "ops" / "daemons"
                if _ops_daemons.is_dir() and str(_ops_daemons) not in _sys.path:
                    _sys.path.append(str(_ops_daemons))
                manifest = json.loads(
                    (root / snapshot["name"] / "manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
                from backup_bot import _backup_file

                status_summary["verified"] = all(
                    _backup_file(root / snapshot["name"], Path(entry["path"]))
                    .stat()
                    .st_size
                    == entry["size"]
                    for entry in manifest["files"]
                )
            except (OSError, ValueError, TypeError, KeyError):
                status_summary["verified"] = False
        else:
            status_summary["verified"] = False
    try:
        age = max(
            0,
            int(
                (
                    datetime.now().astimezone()
                    - datetime.fromisoformat(last["created_at"])
                ).total_seconds()
            ),
        )
    except (ValueError, TypeError, KeyError):
        age = None
    return {
        "available": bool(backups),
        "backups": backups[:10],
        "last": last,
        "invalid_manifests": invalid,
        "age_seconds": age,
        "verification": status_summary,
    }

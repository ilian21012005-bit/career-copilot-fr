"""Adaptateurs d'exécution autonomes pour Career Copilot (avec délégation monorepo optionnelle)."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

BOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BOT_DIR.parent.parent


class WorkloadBusy(RuntimeError):
    """Indique qu'une tâche lourde occupe déjà le verrou d'exécution."""


def recovery_paused(root: Path | None = None) -> dict[str, Any]:
    """Vérifie si les envois sont suspendus suite à une restauration."""
    try:
        from shared.operational_state import (
            recovery_paused as _monorepo_recovery_paused,
        )

        return (
            _monorepo_recovery_paused(root)
            if root is not None
            else _monorepo_recovery_paused()
        )
    except Exception:
        base = Path(root) if root is not None else PROJECT_ROOT
        pause_file = base / "data" / "recovery-pause.json"
        if pause_file.is_file():
            try:
                data = json.loads(pause_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("paused"):
                    return data
            except Exception:
                return {"paused": True, "reason": "recovery_pause_unreadable"}
        return {}


def backup_directory(root: Path | None = None) -> Path:
    """Retourne le répertoire de sauvegardes configuré ou local."""
    try:
        from shared.operational_state import backup_directory as _monorepo_backup_dir

        return (
            _monorepo_backup_dir(root) if root is not None else _monorepo_backup_dir()
        )
    except Exception:
        env_dir = os.getenv("BOTS_BACKUP_DIR", "").strip()
        if env_dir:
            return Path(env_dir)
        base = Path(root) if root is not None else BOT_DIR
        return base / "data" / "backups"


def run_heavy(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | float | None = None,
    scope: str = "career-copilot",
    capture_output: bool = False,
    text: bool = False,
    input: str | bytes | None = None,
) -> subprocess.CompletedProcess[Any]:
    """Exécute un sous-processus lourd avec délégation `shared.workload` si disponible."""
    try:
        from shared.workload import run_heavy as _monorepo_run_heavy

        return _monorepo_run_heavy(
            cmd,
            cwd=cwd,
            env=env,
            timeout=timeout,
            scope=scope,
            capture_output=capture_output,
            text=text,
            input=input,
        )
    except ImportError:
        return subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            timeout=timeout,
            check=False,
            capture_output=capture_output,
            text=text,
            input=input,
        )


class _StandaloneAIFailover:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def state(self) -> dict[str, Any]:
        return dict(self._state)

    def blocked(self) -> bool:
        try:
            return float(self._state.get("retry_at", 0) or 0) > time.time()
        except (TypeError, ValueError):
            return False

    def defer(self, reason: str, seconds: int = 3600) -> None:
        if seconds <= 0:
            self._state = {"reason": str(reason), "retry_at": 0.0}
        else:
            self._state = {"reason": str(reason), "retry_at": time.time() + seconds}

    def attempt(self, fn: Callable[[], str | None]) -> str | None:
        if self.blocked():
            return None
        try:
            return fn()
        except Exception:
            return None


class _StandaloneGeminiAPI:
    MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def enabled(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY", "").strip())

    def ask(
        self,
        prompt: str,
        reserve_fn: Callable[[], bool] | None = None,
        *,
        timeout: int = 30,
    ) -> str | None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            return None
        if reserve_fn is not None and not reserve_fn():
            return None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.MODEL}:generateContent?key={api_key}"
        payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode(
            "utf-8"
        )
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates") or []
                if candidates:
                    parts = ((candidates[0].get("content") or {}).get("parts")) or []
                    if parts and isinstance(parts[0].get("text"), str):
                        return parts[0]["text"].strip()
        except Exception:
            return None
        return None


class _StandaloneOpenRouterAPI:
    MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-31b-it:free")

    def enabled(self) -> bool:
        return bool(os.getenv("OPENROUTER_API_KEY", "").strip())

    def ask(
        self,
        prompt: str,
        reserve_fn: Callable[[], bool] | None = None,
        *,
        timeout: int = 30,
    ) -> str | None:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return None
        if reserve_fn is not None and not reserve_fn():
            return None
        payload = json.dumps(
            {
                "model": self.MODEL,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices") or []
                if choices:
                    msg = (choices[0].get("message") or {}).get("content")
                    if isinstance(msg, str):
                        return msg.strip()
        except Exception:
            return None
        return None


def get_ai_backends() -> tuple[Any, Any, Any]:
    """Retourne `(ai_failover, gemini_api, openrouter_api)` du monorepo ou autonomes."""
    try:
        from shared import ai_failover, gemini_api, openrouter_api

        return ai_failover, gemini_api, openrouter_api
    except Exception:
        return (
            _StandaloneAIFailover(),
            _StandaloneGeminiAPI(),
            _StandaloneOpenRouterAPI(),
        )

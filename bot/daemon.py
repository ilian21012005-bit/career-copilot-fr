#!/usr/bin/env python3
"""
daemon.py — Service d'arrière-plan pour les candidatures (Job-Etudiant).
Exécute le cycle à un ou plusieurs créneaux quotidiens
(défaut: 06:30,12:00,18:00 via SCHEDULE_TIME) et gère l'arrêt propre.
"""

from __future__ import annotations

import argparse
import datetime
import file_lock as fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from shared.workload import WorkloadBusy, run_heavy
except ModuleNotFoundError:

    class WorkloadBusy(RuntimeError):
        """Indique que la capacité locale d'exécution lourde est occupée."""

    def run_heavy(
        cmd: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        cancelled: object | None = None,
        owner_unit: str | None = None,
    ) -> int:
        del owner_unit
        proc = subprocess.Popen(cmd, cwd=cwd, env=env)  # noqa: S603
        deadline = (time.monotonic() + float(timeout)) if timeout is not None else None
        try:
            while True:
                rc = proc.poll()
                if rc is not None:
                    return rc
                if callable(cancelled) and cancelled():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    raise InterruptedError("Exécution annulée")
                if deadline is not None and time.monotonic() >= deadline:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    raise subprocess.TimeoutExpired(cmd, timeout or 0)
                time.sleep(0.25)
        finally:
            if proc.poll() is None:
                proc.kill()


PYTHON = sys.executable
LOG = logging.getLogger("daemon")

running = True
DEFAULT_CYCLE_TIMEOUT = 1800
DEFAULT_SCHEDULE = "06:30,12:00,18:00"


def handle_signal(sig, frame):
    global running
    sig_name = signal.Signals(sig).name
    print(
        f"\n[Job-Etudiant Daemon] Signal {sig_name} reçu, arrêt propre du bot...",
        flush=True,
    )
    running = False


def _state_path() -> Path:
    path = HERE / "data" / "daemon-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def _save_state(data: dict) -> None:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _load_last_run_date() -> datetime.date | None:
    value = _load_state().get("last_run_date")
    try:
        return datetime.date.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def _slots_done_for(day: datetime.date) -> list[str]:
    state = _load_state()
    raw = (state.get("slots_done") or {}).get(day.isoformat()) or []
    return [str(item) for item in raw if isinstance(item, str)]


def _mark_slot_done(day: datetime.date, slot: str) -> None:
    state = _load_state()
    slots_done = dict(state.get("slots_done") or {})
    key = day.isoformat()
    current = list(slots_done.get(key) or [])
    if slot not in current:
        current.append(slot)
    slots_done[key] = current
    # Keep only a few recent days
    if len(slots_done) > 14:
        for old in sorted(slots_done.keys())[:-14]:
            slots_done.pop(old, None)
    state["slots_done"] = slots_done
    state["last_run_date"] = day.isoformat()
    state["last_slot"] = slot
    _save_state(state)


def _retry_path() -> Path:
    return HERE / "data" / "hellowork-retry.json"


def _load_retry_state() -> tuple[float | None, int]:
    try:
        data = json.loads(_retry_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, 0
        raw_at = data.get("retry_at")
        value = float(raw_at) if raw_at is not None else None
        retry_at = value if value is not None and 0 < value < 1e11 else None
        if retry_at is None:
            return None, 0
        attempts = max(0, int(data.get("retry_attempts", 0) or 0))
        return retry_at, attempts
    except (OSError, ValueError, TypeError, KeyError):
        return None, 0


def _save_retry_state(retry_at: float | None, retry_attempts: int = 0) -> None:
    path = _retry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if retry_at is None:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_suffix(".tmp")
    payload = {"retry_at": retry_at, "retry_attempts": max(0, int(retry_attempts))}
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _save_retry_at(value: float | None) -> None:
    if value is None:
        _save_retry_state(None, 0)
        return
    _, attempts = _load_retry_state()
    _save_retry_state(value, attempts)


def _load_retry_at() -> float | None:
    retry_at, _ = _load_retry_state()
    return retry_at


def _load_retry_attempts() -> int:
    _, attempts = _load_retry_state()
    return attempts


def _cycle_timeout() -> int:
    try:
        value = int(os.getenv("BOT_CYCLE_TIMEOUT", str(DEFAULT_CYCLE_TIMEOUT)))
        return max(60, min(value, 24 * 60 * 60))
    except ValueError:
        return DEFAULT_CYCLE_TIMEOUT


def _run_command(cmd: list[str], env: dict[str, str], label: str) -> int:
    try:
        return run_heavy(
            cmd,
            cwd=str(HERE),
            env=env,
            timeout=_cycle_timeout(),
            cancelled=lambda: not running,
            owner_unit="bot-job-etudiant.service",
        )
    except WorkloadBusy:
        print("[Job-Etudiant Daemon] Capacité occupée ; cycle différé.", flush=True)
        return 75
    except InterruptedError:
        return 130
    except subprocess.TimeoutExpired:
        print(
            f"[Job-Etudiant Daemon] {label} dépassé après {_cycle_timeout()}s.",
            flush=True,
        )
        return 124
    except OSError as exc:
        print(f"[Job-Etudiant Daemon] {label} impossible à lancer : {exc}", flush=True)
        return 127


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    parts = [str(HERE), str(PROJECT_ROOT)]
    existing = env.get("PYTHONPATH", "")
    if existing:
        parts.extend(p for p in existing.split(os.pathsep) if p and p not in parts)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def _notify_automation(bot: str, action: str, status: str, **kwargs) -> None:
    try:
        import notifier

        notifier.notify_automation(bot, action, status, **kwargs)
    except Exception as exc:
        LOG.warning("Notification automation échouée (%s %s): %s", action, status, exc)


def _record_hw_cycle_outcome(hw_code: int, *, slot: str | None = None) -> int:
    """Suit les échecs consécutifs HelloWork et alerte explicitement dès 2 créneaux consécutifs."""
    state = _load_state()
    if hw_code == 0:
        if state.get("consecutive_hw_failures"):
            state["consecutive_hw_failures"] = 0
            _save_state(state)
        return 0
    streak = max(0, int(state.get("consecutive_hw_failures", 0) or 0)) + 1
    state["consecutive_hw_failures"] = streak
    _save_state(state)
    if streak >= 2:
        try:
            import notifier

            slot_txt = f" (créneau {slot})" if slot else ""
            notifier.send_telegram(
                f"⚠️ <b>Alerte Job-Etudiant</b> : {streak} échecs consécutifs du cycle HelloWork{slot_txt} (code {hw_code})."
            )
        except Exception as exc:
            LOG.warning("Alerte Telegram HelloWork échouée : %s", exc)
    return streak


def run_cycle(args_list: list[str], *, slot: str | None = None) -> int:
    env = _subprocess_env()
    action = f"créneau {slot}" if slot else "cycle"
    mode = "envoi réel" if "--send" in args_list else "dry-run"
    started = time.time()
    _notify_automation("JE", action, "started", summary=f"Mode {mode}")
    main_args = list(args_list)
    if "--skip-public-ats" not in main_args:
        main_args.append("--skip-public-ats")
    cmd = [PYTHON, str(HERE / "main.py")] + main_args
    label_slot = f" (créneau {slot})" if slot else ""
    print(
        f"[Job-Etudiant Daemon] [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"
        f" Lancement du cycle multi-sources{label_slot} : {' '.join(cmd)}",
        flush=True,
    )
    main_code = _run_command(cmd, env, "Cycle multi-sources")
    print(
        f"[Job-Etudiant Daemon] Cycle multi-sources terminé avec code {main_code}",
        flush=True,
    )
    if main_code != 0:
        print(
            f"[Job-Etudiant Daemon] Échec multi-sources (code {main_code}) ; poursuite du cycle HelloWork.",
            flush=True,
        )
        _notify_automation(
            "JE",
            action,
            "failed",
            summary=f"Multi-sources code {main_code} · mode {mode}",
            duration_s=time.time() - started,
            code=main_code,
        )

    hw_args = ["-m", "hellowork", "daily", "--if-due"]
    if "--send" in args_list:
        hw_args.append("--auto-submit")
    cmd_hw = [PYTHON] + hw_args
    print(
        f"[Job-Etudiant Daemon] Lancement du cycle HelloWork : {' '.join(cmd_hw)}",
        flush=True,
    )
    hw_code = _run_command(cmd_hw, env, "Cycle HelloWork")
    print(f"[Job-Etudiant Daemon] Cycle HelloWork terminé avec code {hw_code}", flush=True)
    _record_hw_cycle_outcome(hw_code, slot=slot)
    flush_code = 0
    if hw_code == 0 and "--send" in args_list:
        cmd_flush = [PYTHON, str(HERE / "main.py"), "--flush-queue", "--send"]
        flush_code = _run_command(cmd_flush, env, "Flush file mail_queue")
        print(
            f"[Job-Etudiant Daemon] Flush mail_queue terminé avec code {flush_code}",
            flush=True,
        )

    res = 1 if hw_code else main_code or flush_code
    duration = time.time() - started
    if res == 0:
        _notify_automation(
            "JE",
            action,
            "finished",
            summary=f"Multi-sources OK · HelloWork OK · mode {mode}",
            duration_s=duration,
            code=0,
        )
    elif hw_code or flush_code:
        _notify_automation(
            "JE",
            action,
            "failed",
            summary=f"HelloWork code {hw_code} · file SMTP code {flush_code} · mode {mode}",
            duration_s=duration,
            code=hw_code or flush_code,
        )
    return res


def retry_discovery() -> int:
    """Retry discovery and preparation without replaying any automatic submission."""
    env = _subprocess_env()
    print("[Job-Etudiant Daemon] Reprise HelloWork sans envoi automatique.", flush=True)
    return _run_command([PYTHON, "-m", "hellowork", "daily"], env, "Reprise HelloWork")


def get_target_time(time_str: str) -> tuple[int, int]:
    try:
        parts = time_str.strip().split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except (ValueError, IndexError):
        return 6, 30


MAX_SCHEDULE_SLOTS = 8


def parse_schedule_times(raw: str | None) -> list[str]:
    """Parse 'HH:MM' or 'HH:MM,HH:MM,...' into sorted unique slots."""
    text = (raw or "").strip() or DEFAULT_SCHEDULE
    slots: list[str] = []
    seen: set[str] = set()
    for part in text.replace(";", ",").split(","):
        piece = part.strip()
        if not piece:
            continue
        hour, minute = get_target_time(piece)
        # Reject clearly invalid inputs that fell back only when the piece itself was invalid
        try:
            h, m = int(piece.split(":")[0]), int(piece.split(":")[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                continue
        except (ValueError, IndexError):
            continue
        label = f"{hour:02d}:{minute:02d}"
        if label not in seen:
            seen.add(label)
            slots.append(label)
        if len(slots) >= MAX_SCHEDULE_SLOTS:
            break
    slots.sort(key=lambda s: get_target_time(s))
    return slots or ["06:30"]


def slot_reached(now: datetime.datetime, slot: str) -> bool:
    hour, minute = get_target_time(slot)
    return now.hour > hour or (now.hour == hour and now.minute >= minute)


def next_due_slot(now: datetime.datetime, schedule: list[str], done: list[str]) -> str | None:
    for slot in schedule:
        if slot in done:
            continue
        if slot_reached(now, slot):
            return slot
    return None


def due_slots(now: datetime.datetime, schedule: list[str], done: list[str]) -> list[str]:
    return [slot for slot in schedule if slot not in done and slot_reached(now, slot)]


def select_slot_to_run(
    now: datetime.datetime, schedule: list[str], done: list[str]
) -> tuple[str | None, list[str]]:
    """Run only the latest due slot; older missed slots are skipped (no catch-up burst)."""
    pending = due_slots(now, schedule, done)
    if not pending:
        return None, []
    return pending[-1], pending[:-1]


def _migrate_legacy_slots(
    schedule: list[str], today: datetime.date, now: datetime.datetime
) -> list[str]:
    """Si l'ancien mode 1×/jour a déjà tourné aujourd'hui, ne pas rejouer les créneaux passés."""
    state = _load_state()
    key = today.isoformat()
    slots_done = dict(state.get("slots_done") or {})
    if key in slots_done:
        return [str(s) for s in slots_done[key] if isinstance(s, str)]
    if state.get("last_run_date") == key:
        past = [slot for slot in schedule if slot_reached(now, slot)]
        seeded = past or ([schedule[0]] if schedule else [])
        slots_done[key] = seeded
        state["slots_done"] = slots_done
        _save_state(state)
        return list(seeded)
    return []


def _persist_slots_done(day: datetime.date, slots: list[str]) -> None:
    """Mark several slots done in one write (boot recovery / catch-up skip)."""
    for slot in slots:
        _mark_slot_done(day, slot)


def _handle_cycle_result(today: datetime.date, slot: str, result: int) -> float | None:
    """Always consume the slot (success or failure) to avoid --send re-fire every ~30s."""
    _mark_slot_done(today, slot)
    if result == 0:
        _save_retry_state(None, 0)
        return None
    _, attempts = _load_retry_state()
    retry_at = time.time() + 1800
    _save_retry_state(retry_at, attempts)
    print(
        f"[Job-Etudiant Daemon] Créneau {slot} en échec (code {result}) ; "
        "créneau consommé, reprise HelloWork sans auto-submit dans 30 min.",
        flush=True,
    )
    return retry_at


def _run_pending_retry(retry_attempts: int, max_retries: int) -> tuple[float | None, int]:
    result = retry_discovery()
    if result == 0:
        print(
            "[Job-Etudiant Daemon] Reprise réussie ; vérifier les candidatures avant envoi.",
            flush=True,
        )
        _save_retry_state(None, 0)
        return None, 0
    if result in (75, 130):
        retry_at = time.time() + 1800
        _save_retry_state(retry_at, retry_attempts)
        return retry_at, retry_attempts
    retry_attempts += 1
    if retry_attempts >= max_retries:
        print(
            f"[Job-Etudiant Daemon] Reprise abandonnée après {max_retries} échecs consécutifs.",
            flush=True,
        )
        _save_retry_state(None, 0)
        return None, 0
    retry_at = time.time() + 1800
    _save_retry_state(retry_at, retry_attempts)
    return retry_at, retry_attempts


def main():
    global running
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    parser = argparse.ArgumentParser(description="Daemon Job-Etudiant")
    parser.add_argument("--send", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--time",
        default=os.getenv("SCHEDULE_TIME", DEFAULT_SCHEDULE),
        help="Créneau(x) quotidien(s) HH:MM ou HH:MM,HH:MM,...",
    )
    parser.add_argument(
        "--skip-initial",
        action="store_true",
        help="Ne pas lancer immédiatement au démarrage",
    )
    args = parser.parse_args()

    mode_arg = ["--send"] if args.send or os.getenv("AUTOPILOT_SEND") == "1" else ["--dry-run"]
    LOCK_PATH = HERE / "data" / "daemon.lock"
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        LOCK_PATH.parent.chmod(0o700)
    lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    if os.name != "nt":
        os.chmod(LOCK_PATH, 0o600)
    lock_fh = os.fdopen(lock_fd, "w+", encoding="utf-8")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(
            "[Job-Etudiant Daemon] Une autre instance tourne déjà (daemon.lock verrouillé).",
            flush=True,
        )
        lock_fh.close()
        return 1

    schedule = parse_schedule_times(args.time)

    print(
        f"[Job-Etudiant Daemon] Service démarré. Créneaux : {', '.join(schedule)}. Mode : {' '.join(mode_arg)}",
        flush=True,
    )

    retry_at, retry_attempts = _load_retry_state()
    max_retries = 6
    today = datetime.date.today()
    now = datetime.datetime.now()
    done_today = _migrate_legacy_slots(schedule, today, now)

    stale_retry = retry_at is not None and _load_last_run_date() != today
    if stale_retry:
        # Une reprise en attente depuis la veille passe avant un nouveau cycle,
        # mais elle ne doit pas consommer les créneaux du jour.
        print("[Job-Etudiant Daemon] Reprise en attente depuis la veille.", flush=True)
        if retry_at is not None and time.time() >= retry_at:
            retry_at, retry_attempts = _run_pending_retry(retry_attempts, max_retries)

    if args.skip_initial:
        due_init, skipped_init = select_slot_to_run(now, schedule, done_today)
        to_skip = list(skipped_init) + ([due_init] if due_init else [])
        if to_skip:
            _persist_slots_done(today, to_skip)
            done_today = _slots_done_for(today)
            print(
                f"[Job-Etudiant Daemon] --skip-initial : créneau(x) initial(aux) ignoré(s) ({', '.join(to_skip)}).",
                flush=True,
            )
    elif not stale_retry:
        due, skipped = select_slot_to_run(datetime.datetime.now(), schedule, done_today)
        if skipped:
            _persist_slots_done(today, skipped)
        if due:
            result = run_cycle(mode_arg, slot=due)
            retry_at = _handle_cycle_result(today, due, result)
            _, retry_attempts = _load_retry_state()

    while running:
        now = datetime.datetime.now()
        today = now.date()
        done_today = _slots_done_for(today)
        if not done_today:
            done_today = _migrate_legacy_slots(schedule, today, now)

        due, skipped = select_slot_to_run(now, schedule, done_today)
        if skipped:
            _persist_slots_done(today, skipped)
            print(
                f"[Job-Etudiant Daemon] Rattrapage limité : créneaux ignorés {', '.join(skipped)} ; "
                f"exécution de {due}.",
                flush=True,
            )
        if due:
            result = run_cycle(mode_arg, slot=due)
            retry_at = _handle_cycle_result(today, due, result)
            _, retry_attempts = _load_retry_state()

        if retry_at is not None and time.time() >= retry_at:
            retry_at, retry_attempts = _run_pending_retry(retry_attempts, max_retries)

        for _ in range(6):
            if not running:
                break
            time.sleep(5)

    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    finally:
        lock_fh.close()
    print("[Job-Etudiant Daemon] Arrêt terminé avec succès.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

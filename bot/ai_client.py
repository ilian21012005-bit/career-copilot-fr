"""Client IA distant à quota, avec secours déterministe si indisponible."""
from __future__ import annotations

import file_lock as fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from runtime_hooks import get_ai_backends
from private_storage import ensure_private_directory, protect_private_file, write_private_text

ai_failover, gemini_api, openrouter_api = get_ai_backends()

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
CACHE_FILE = DATA_DIR / "ai_cache.json"
USAGE_FILE = DATA_DIR / "ai_usage.json"
LOG = logging.getLogger("ai_client")

DEFAULT_MODEL = os.getenv("AI_DEFAULT_MODEL", "gemini-3.8-flash-low")
PROSE_MODEL = os.getenv("AI_PROSE_MODEL", DEFAULT_MODEL)


def _setting(name: str, default: str) -> str:
    if name in os.environ:
        return os.environ[name]
    for path in (HERE / ".env", HERE.parent.parent / ".env"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
    return default


ALLOW_AI = _setting("AI_ENABLED", "0").strip().lower() in {"1", "true", "yes"} and _setting(
    "AI_ALLOW_PAID_API", "0"
).strip().lower() not in {"1", "true", "yes"}
try:
    MAX_CALLS_PER_DAY = max(0, min(int(_setting("AI_MAX_CALLS_PER_DAY", "100")), 500))
except ValueError:
    MAX_CALLS_PER_DAY = 0
ALLOW_PAID_API = False

ROUTE = _setting("AI_ROUTE", "hybrid").strip().lower() or "hybrid"

PROSE_TASKS = {"prose", "letter", "lm", "cover", "motivation", "cv"}
BULK_TASKS = {"bulk", "classify", "tag", "score", "summarize", "extract"}


def _reserve_call() -> bool:
    """Reserve a daily agy call slot atomically."""
    if getattr(ai_failover, "blocked", lambda: False)():
        return False
    try:
        ensure_private_directory(DATA_DIR)
        lock = USAGE_FILE.with_suffix(".lock")
        if lock.is_symlink():
            return False
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except (OSError, ValueError):
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    try:
        try:
            if USAGE_FILE.is_symlink():
                return False
            if USAGE_FILE.exists():
                protect_private_file(USAGE_FILE)
            usage = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            usage = {}
        except (OSError, ValueError):
            return False
        today = date.today().isoformat()
        try:
            count = int(usage.get("date") == today and usage.get("calls", 0) or 0)
            if count < 0:
                return False
        except (AttributeError, TypeError, ValueError, OverflowError):
            return False
        if count >= MAX_CALLS_PER_DAY:
            return False
        try:
            write_private_text(USAGE_FILE, json.dumps({"date": today, "calls": count + 1}))
        except (OSError, ValueError):
            return False
        return True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def daily_quota_reached() -> bool:
    """Indique si le plafond quotidien local d'appels IA est atteint aujourd'hui."""
    if MAX_CALLS_PER_DAY <= 0:
        return False
    try:
        if USAGE_FILE.is_symlink():
            return False
        usage = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return False
    if not isinstance(usage, dict) or usage.get("date") != date.today().isoformat():
        return False
    try:
        calls = int(usage.get("calls", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return calls >= MAX_CALLS_PER_DAY


def _load_cache() -> dict[str, str]:
    if CACHE_FILE.exists():
        try:
            if CACHE_FILE.is_symlink():
                return {}
            protect_private_file(CACHE_FILE)
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    try:
        ensure_private_directory(DATA_DIR)
        if len(cache) > 500:
            keys = list(cache.keys())[-500:]
            cache = {k: cache[k] for k in keys}
        write_private_text(CACHE_FILE, json.dumps(cache, ensure_ascii=False, indent=2))
    except Exception:
        pass


def compact_prompt(prompt: str) -> str:
    """Compacte les espaces et sauts de ligne redondants pour économiser 8 à 15 % de tokens sans perte sémantique."""
    if not prompt:
        return ""
    lines = [line.rstrip() for line in prompt.strip().splitlines()]
    out: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(line)
            blank = False
    return "\n".join(out)


def _cache_key(prompt: str, model: str) -> str:
    return hashlib.sha256(f"{model}:{compact_prompt(prompt)}".encode("utf-8")).hexdigest()[:24]


def _agy_disabled_today() -> bool:
    try:
        return (
            json.loads((DATA_DIR / "ai_disabled_until.json").read_text(encoding="utf-8")).get("date")
            == date.today().isoformat()
        )
    except (OSError, ValueError, TypeError):
        return False


def _disable_ai_until_tomorrow() -> None:
    ai_failover.defer("provider_limit", 6 * 3600)
    try:
        ensure_private_directory(DATA_DIR)
        state = DATA_DIR / "ai_disabled_until.json"
        write_private_text(state, json.dumps({"date": date.today().isoformat(), "reason": "provider_limit"}))
    except (OSError, ValueError):
        pass


_AGY_PROFILE_ORDER = ("b", "a", "c")
_AGY_TOKEN_REL = Path(".gemini") / "antigravity-cli" / "antigravity-oauth-token"
_AGY_QUOTA_MARKERS = ("quota exceeded", "resource_exhausted", "billing", "rate limit", "429")
_AGY_SLOT_COOLDOWN_SECONDS = 3600
_AGY_COOLDOWN_LOCK = threading.Lock()
_AGY_SLOT_COOLDOWNS: dict[str, float] = {}


def _agy_profiles_root() -> Path:
    configured = os.getenv("OPENCODE_AGY_PROFILES", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local" / "share" / "opencode" / "agy-profiles"


def _agy_slot_ready(slot_dir: Path, now: float | None = None) -> bool:
    key = str(slot_dir)
    current = time.time() if now is None else now
    with _AGY_COOLDOWN_LOCK:
        until = _AGY_SLOT_COOLDOWNS.get(key, 0.0)
        if until <= current:
            _AGY_SLOT_COOLDOWNS.pop(key, None)
            return True
        return False


def _mark_agy_slot_cooldown(slot_dir: Path, seconds: int = _AGY_SLOT_COOLDOWN_SECONDS) -> None:
    key = str(slot_dir)
    until = time.time() + max(1, seconds)
    with _AGY_COOLDOWN_LOCK:
        _AGY_SLOT_COOLDOWNS[key] = until


def _discover_agy_profiles(*, include_cooling: bool = False) -> list[Path]:
    """Découvre les profils agy isolés avec jeton OAuth dans l'ordre free-first."""
    root = _agy_profiles_root()
    if not root.is_dir():
        return []
    slots: list[Path] = []
    now = time.time()
    for name in _AGY_PROFILE_ORDER:
        slot_dir = root / name
        if not slot_dir.is_dir():
            continue
        if not (slot_dir / _AGY_TOKEN_REL).is_file():
            continue
        if include_cooling or _agy_slot_ready(slot_dir, now=now):
            slots.append(slot_dir)
    return slots


def _build_agy_slot_env(base_env: dict[str, str], slot_dir: Path) -> dict[str, str]:
    slot_env = base_env.copy()
    run_dir = slot_dir / ".run"
    try:
        run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        pass
    slot_env["HOME"] = str(slot_dir)
    slot_env["XDG_CONFIG_HOME"] = str(slot_dir / ".config")
    slot_env["XDG_CACHE_HOME"] = str(slot_dir / ".cache")
    slot_env["XDG_DATA_HOME"] = str(slot_dir / ".local" / "share")
    slot_env["XDG_RUNTIME_DIR"] = str(run_dir)
    slot_env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent"
    return slot_env


def _clean_agy_output(stdout: str) -> str:
    out = stdout.strip()
    lines = [
        line
        for line in out.splitlines()
        if not line.startswith(("⠋", "⠙", "⠹", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"))
    ]
    cleaned = "\n".join(lines).strip()
    return cleaned if cleaned else out


_HEADLESS_AGY_SETTINGS = '{"useG1Credits":false}'


def _headless_agy_cwd() -> Path:
    """Retourne un répertoire vide hors dépôt pour isoler `agy -p` des rules/skills workspace."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    cwd = Path(tempfile.gettempdir()) / f"career-copilot-agy-headless-{uid}"
    cwd.mkdir(mode=0o700, parents=True, exist_ok=True)
    return cwd


def _run_agy_once(
    agy_path: str, prompt: str, model: str, timeout: int, env: dict[str, str]
) -> tuple[str | None, bool]:
    bounded_timeout = max(1, int(timeout))
    cmd = [
        agy_path,
        "--model",
        model,
        "--disable-slash-commands",
        "--print-timeout",
        f"{bounded_timeout}s",
        "--settings",
        _HEADLESS_AGY_SETTINGS,
        "-p",
        prompt,
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(_headless_agy_cwd()),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, False
    diagnostic = f"{res.stdout}\n{res.stderr}".lower()
    if any(marker in diagnostic for marker in _AGY_QUOTA_MARKERS):
        return None, True
    if res.returncode == 0 and res.stdout.strip():
        return _clean_agy_output(res.stdout), False
    return None, False


def _call_agy_cli(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 30) -> str | None:
    """Appel CLI agy (compte / quota), avec failover entre profils isolés si présents."""
    local_bin = str(Path.home() / ".local" / "bin")
    env = os.environ.copy()
    if local_bin not in env.get("PATH", "").split(os.pathsep):
        env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
    agy_path = shutil.which("agy", path=env.get("PATH"))
    if not agy_path:
        default_agy = Path.home() / ".local" / "bin" / "agy"
        if default_agy.exists():
            agy_path = str(default_agy)
    if not agy_path:
        return None

    use_profiles = os.getenv("AGY_USE_PROFILES", "1").strip() != "0"
    all_slots = _discover_agy_profiles(include_cooling=True) if use_profiles else []
    if all_slots:
        ready_slots = [slot for slot in all_slots if _agy_slot_ready(slot)]
        if not ready_slots:
            _disable_ai_until_tomorrow()
            return None
        quota_failures = 0
        for slot_dir in ready_slots:
            slot_env = _build_agy_slot_env(env, slot_dir)
            output, is_quota = _run_agy_once(agy_path, prompt, model, timeout, slot_env)
            if output:
                return output
            if is_quota:
                quota_failures += 1
                _mark_agy_slot_cooldown(slot_dir)
                LOG.info("agy slot=%s en cooldown (quota)", slot_dir.name)
        if quota_failures == len(ready_slots):
            _disable_ai_until_tomorrow()
        return None

    output, is_quota = _run_agy_once(agy_path, prompt, model, timeout, env)
    if is_quota:
        _disable_ai_until_tomorrow()
        return None
    return output


def _call_agy_reserved(prompt: str, model: str, timeout: int) -> str | None:
    if not ALLOW_AI or MAX_CALLS_PER_DAY == 0:
        return None
    def call():
        if not _reserve_call():
            return None
        return _call_agy_cli(prompt[:12000], model=model, timeout=min(timeout, 90))
    return ai_failover.attempt(call)


def _route_order(task: str) -> list[str]:
    # L'ancienne route locale reste stricte : aucune sortie distante implicite.
    if ROUTE == "local":
        return []
    if ROUTE == "agy":
        return ["agy"]
    backends = []
    if gemini_api.enabled():
        backends.append("gemini")
    if openrouter_api.enabled():
        backends.append("openrouter")
    return backends or ["agy"]


def ask_ai(
    prompt: str,
    model: str = DEFAULT_MODEL,
    use_cache: bool = True,
    timeout: int = 30,
    fallback_model: str | None = None,
    task: str = "bulk",
    local_model: str | None = None,
) -> str | None:
    """Interroge les fournisseurs distants selon la route configurée.

    Renvoie le texte ou None si indisponible.
    """
    if not prompt or len(prompt) > 12000 or ROUTE == "local" or os.environ.get("DISABLE_AI", "").strip().lower() in {"1", "true", "yes"} or not ALLOW_AI:
        return None
    backends = _route_order(task)
    cache_model = f"v2|{model}|{task}|{ROUTE}|{backends}|{gemini_api.MODEL}|{openrouter_api.MODEL}"
    key = _cache_key(prompt, cache_model)
    if use_cache:
        cache = _load_cache()
        if key in cache:
            return cache[key]

    if not ALLOW_AI:
        return None

    res = None
    used = None
    for backend in backends:
        if backend == "gemini":
            res = gemini_api.ask(prompt, _reserve_call, timeout=timeout)
            used = "gemini" if res else used
        elif backend == "openrouter":
            res = openrouter_api.ask(prompt, _reserve_call, timeout=timeout)
            used = "openrouter" if res else used
        elif backend == "agy":
            res = _call_agy_reserved(prompt, model=model, timeout=timeout)
            used = "agy" if res else used
        if res:
            break

    if res and use_cache and backends and used == backends[0]:
        cache = _load_cache()
        cache[key] = res
        _save_cache(cache)
    if res:
        LOG.info("ask_ai ok via=%s task=%s chars=%s", used, task, len(res))
    return res


def status() -> dict:
    return {
        "allow_ai": ALLOW_AI,
        "route": ROUTE,
        "local_up": False,
        "agy_disabled_today": ai_failover.blocked(),
        "agy_state": ai_failover.state(),
        "max_calls_per_day": MAX_CALLS_PER_DAY,
        "default_model": DEFAULT_MODEL,
        "prose_model": PROSE_MODEL,
    }

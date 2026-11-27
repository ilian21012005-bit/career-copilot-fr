"""Verrouillage de fichiers multi-plateforme (POSIX fcntl / Windows msvcrt)."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Any

try:
    import fcntl as _fcntl
except ImportError:  # Windows / non-POSIX
    _fcntl = None  # type: ignore[assignment]

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None  # type: ignore[assignment]

LOCK_EX = getattr(_fcntl, "LOCK_EX", 2)
LOCK_SH = getattr(_fcntl, "LOCK_SH", 1)
LOCK_NB = getattr(_fcntl, "LOCK_NB", 4)
LOCK_UN = getattr(_fcntl, "LOCK_UN", 8)


def _fileno(target: int | IO[Any]) -> int:
    return target if isinstance(target, int) else int(target.fileno())


def flock(target: int | IO[Any], flags: int) -> None:
    """Applique ou relâche un verrou fichier compatible POSIX et Windows."""
    fd = _fileno(target)
    if _fcntl is not None:
        _fcntl.flock(fd, flags)
        return
    if _msvcrt is not None:
        try:
            if flags & LOCK_UN:
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
            elif flags & LOCK_NB:
                _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            else:
                _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc


@contextlib.contextmanager
def locked_file(
    path: Path | str,
    *,
    non_blocking: bool = False,
    mode: int = 0o600,
) -> Iterator[int]:
    """Context manager ouvrant et verrouillant `path` de manière portable."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            target.parent.chmod(0o700)
    fd = os.open(target, os.O_CREAT | os.O_RDWR, mode)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            os.fchmod(fd, mode)
    flags = LOCK_EX | (LOCK_NB if non_blocking else 0)
    try:
        flock(fd, flags)
    except BaseException:
        os.close(fd)
        raise
    try:
        yield fd
    finally:
        with contextlib.suppress(OSError):
            flock(fd, LOCK_UN)
        os.close(fd)

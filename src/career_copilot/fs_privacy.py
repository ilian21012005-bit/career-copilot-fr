"""Private filesystem helpers (owner-only 0700/0600, atomic writes, symlink refusal)."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def ensure_private_directory(path: Path, *, trusted_root: Path | None = None) -> None:
    """Create and restrict a directory tree to owner-only access (0700)."""
    target = path.absolute()
    if trusted_root is not None:
        root = trusted_root.absolute()
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise ValueError("Chemin privé hors de la racine autorisée") from exc
        if ".." in relative.parts:
            raise ValueError("Chemin privé invalide")
        if root.is_symlink():
            raise ValueError("Répertoire racine symbolique interdit")
        current = root
        for component in (None, *relative.parts):
            if component is not None:
                current = current / component
            if current.is_symlink():
                raise ValueError("Répertoire privé symbolique interdit")
            current.mkdir(parents=False, exist_ok=True, mode=0o700)
            if os.name != "nt":
                current.chmod(0o700)
        return

    missing: list[Path] = []
    probe = target
    while not probe.exists():
        missing.append(probe)
        if probe == probe.parent:
            break
        probe = probe.parent
    if probe.is_symlink():
        raise ValueError("Répertoire privé symbolique interdit")
    for directory in reversed(missing):
        directory.mkdir(parents=False, exist_ok=True, mode=0o700)
        if os.name != "nt":
            directory.chmod(0o700)
    if target.is_symlink():
        raise ValueError("Répertoire privé symbolique interdit")


def protect_private_file(path: Path, *, trusted_root: Path | None = None) -> None:
    """Ensure parent is private and restrict an existing file to mode 0600."""
    ensure_private_directory(path.parent, trusted_root=trusted_root)
    if path.is_symlink():
        raise ValueError("Fichier privé symbolique interdit")
    if path.exists() and os.name != "nt":
        path.chmod(0o600)


def write_private_bytes(
    path: Path,
    content: bytes,
    *,
    trusted_root: Path | None = None,
) -> None:
    """Atomically write a private file in mode 0600 with symlink refusal."""
    if path.is_symlink():
        raise ValueError("Lien symbolique interdit pour le fichier privé")
    ensure_private_directory(path.parent, trusted_root=trusted_root)
    parent = path.parent.absolute()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def write_private_text(
    path: Path,
    content: str,
    *,
    trusted_root: Path | None = None,
) -> None:
    """Atomically write UTF-8 text in mode 0600."""
    write_private_bytes(path, content.encode("utf-8"), trusted_root=trusted_root)

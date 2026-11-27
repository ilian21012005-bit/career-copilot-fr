"""Private, atomic persistence for candidate documents and application data."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parent / "data"


def ensure_private_directory(path: Path, *, trusted_root: Path | None = None) -> None:
    """Create/chmod a directory tree below bot/data to owner-only access."""
    root = (trusted_root or DATA_ROOT).absolute()
    target = path.absolute()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Stockage candidat hors de bot/data") from exc
    if ".." in relative.parts:
        raise ValueError("Chemin candidat invalide")
    if root.is_symlink():
        raise ValueError("Répertoire data symbolique interdit")
    current = root
    for component in (None, *relative.parts):
        if component is not None:
            current = current / component
        if current.is_symlink():
            raise ValueError("Répertoire candidat symbolique interdit")
        current.mkdir(parents=False, exist_ok=True, mode=0o700)
        if os.name != "nt":
            current.chmod(0o700)


def write_private_bytes(path: Path, content: bytes) -> None:
    """Atomically write a private file with mode 0600 below bot/data."""
    ensure_private_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def write_private_text(path: Path, content: str) -> None:
    write_private_bytes(path, content.encode("utf-8"))


def copy_private_file(source: Path, destination: Path) -> None:
    """Copy a private source into bot/data without inheriting permissive mode."""
    write_private_bytes(destination, source.read_bytes())


def protect_private_file(path: Path, *, trusted_root: Path | None = None) -> None:
    """Restrict an externally generated file already inside bot/data."""
    ensure_private_directory(path.parent, trusted_root=trusted_root)
    if path.is_symlink():
        raise ValueError("Fichier candidat symbolique interdit")
    if path.exists() and os.name != "nt":
        path.chmod(0o600)

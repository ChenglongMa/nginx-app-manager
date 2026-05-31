"""Filesystem and permission helpers."""

from __future__ import annotations

import os
from pathlib import Path


def is_root() -> bool:
    """Return true when running as root on POSIX systems."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def can_write_path(path: Path) -> bool:
    """Best-effort write permission check for a path or its nearest existing parent."""
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return os.access(candidate, os.W_OK)


def unlink_if_exists(path: Path) -> None:
    """Remove a regular file or symlink if it exists, including broken symlinks."""
    if path.exists() or path.is_symlink():
        path.unlink()

# What: SHA-256 helpers used to fingerprint downloaded files and stored data.
# In: bytes or a file path. Out: a hex digest.
"""Hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    """SHA-256 of a byte string."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()

# What: saves and loads the Fyers access token (it expires every day).
# In: a token string, or a file path.
# Out: the token saved in a small text file, or the token read back (None if there is no file).
"""Token store: one place that reads and writes access_token.txt."""

from __future__ import annotations

from pathlib import Path

DEFAULT_TOKEN_PATH = Path("access_token.txt")


def save_token(token: str, path: Path = DEFAULT_TOKEN_PATH) -> None:
    """Write the token to disk; the file is git-ignored and must never be shared."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")


def load_token(path: Path = DEFAULT_TOKEN_PATH) -> str | None:
    """Return the saved token, or None if there is no file or it is empty."""
    if not path.is_file():
        return None
    token = path.read_text(encoding="utf-8").strip()
    return token or None

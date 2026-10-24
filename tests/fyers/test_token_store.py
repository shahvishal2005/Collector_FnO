# What: tests saving and loading the daily access token.
# In: temporary folders.
# Out: pass/fail results.
from __future__ import annotations

from pathlib import Path

from collector.fyers.token_store import load_token, save_token


def test_save_then_load(tmp_path: Path) -> None:
    path = tmp_path / "access_token.txt"
    save_token("abc.def", path)
    assert load_token(path) == "abc.def"


def test_missing_file_gives_none(tmp_path: Path) -> None:
    assert load_token(tmp_path / "nope.txt") is None


def test_empty_file_gives_none(tmp_path: Path) -> None:
    path = tmp_path / "access_token.txt"
    path.write_text("  \n", encoding="utf-8")
    assert load_token(path) is None


def test_whitespace_is_stripped(tmp_path: Path) -> None:
    path = tmp_path / "access_token.txt"
    save_token("  tok\n", path)
    assert path.read_text(encoding="utf-8") == "tok"


def test_parent_folder_is_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "tok.txt"
    save_token("x", path)
    assert load_token(path) == "x"

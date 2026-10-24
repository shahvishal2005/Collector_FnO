# What: tests that the session reuses a valid token and falls back in the right order.
# In: fake secrets and fake login/validate functions.
# Out: pass/fail results.
from __future__ import annotations

from pathlib import Path

import pytest

from collector.fyers import session
from collector.fyers.errors import AuthError
from collector.fyers.secrets import FyersSecrets, load_secrets
from collector.fyers.session import get_access_token
from collector.fyers.token_store import load_token, save_token
from tests.helpers import FAKE_ENV


def _secrets() -> FyersSecrets:
    return load_secrets(FAKE_ENV)


def _boom(secrets: FyersSecrets) -> str:
    raise AssertionError("login must not be called")


def _fail(secrets: FyersSecrets) -> str:
    raise AuthError("endpoint changed")


def test_valid_saved_token_is_reused_without_login(tmp_path: Path) -> None:
    path = tmp_path / "tok.txt"
    save_token("saved", path)
    token = get_access_token(
        _secrets(), path, validate=lambda s, t: True, totp_login=_boom, browser_login=_boom
    )
    assert token == "saved"


def test_stale_token_triggers_totp_login_and_is_saved(tmp_path: Path) -> None:
    path = tmp_path / "tok.txt"
    save_token("old", path)
    token = get_access_token(
        _secrets(),
        path,
        validate=lambda s, t: False,
        totp_login=lambda s: "fresh",
        browser_login=_boom,
    )
    assert token == "fresh" and load_token(path) == "fresh"


def test_no_saved_token_logs_in(tmp_path: Path) -> None:
    path = tmp_path / "tok.txt"
    token = get_access_token(
        _secrets(),
        path,
        validate=lambda s, t: True,
        totp_login=lambda s: "new",
        browser_login=_boom,
    )
    assert token == "new"


def test_totp_failure_without_browser_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="interactively"):
        get_access_token(
            _secrets(),
            tmp_path / "tok.txt",
            validate=lambda s, t: False,
            totp_login=_fail,
            browser_login=_boom,
        )


def test_totp_failure_with_browser_allowed_uses_fallback(tmp_path: Path) -> None:
    path = tmp_path / "tok.txt"
    token = get_access_token(
        _secrets(),
        path,
        allow_browser=True,
        validate=lambda s, t: False,
        totp_login=_fail,
        browser_login=lambda s: "from-browser",
    )
    assert token == "from-browser" and load_token(path) == "from-browser"


def test_token_check_treats_any_exception_as_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(secrets: FyersSecrets, token: str, log_dir: Path | None = None) -> object:
        raise RuntimeError("sdk exploded")

    monkeypatch.setattr(session, "build_client", broken)
    assert session.token_is_valid(_secrets(), "tok") is False


def test_token_check_true_only_for_ok_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    class Client:
        def __init__(self, answer: dict[str, str]) -> None:
            self.answer = answer

        def get_profile(self) -> dict[str, str]:
            return self.answer

    monkeypatch.setattr(session, "build_client", lambda s, t, log_dir=None: Client({"s": "ok"}))
    assert session.token_is_valid(_secrets(), "tok") is True
    monkeypatch.setattr(session, "build_client", lambda s, t, log_dir=None: Client({"s": "error"}))
    assert session.token_is_valid(_secrets(), "tok") is False

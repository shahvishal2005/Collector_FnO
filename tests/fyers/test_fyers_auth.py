# What: tests the automatic TOTP login with every network call faked.
# In: fake secrets and a fake post function that records each call.
# Out: pass/fail results.
from __future__ import annotations

import base64
from typing import Any

import pytest
import requests

from collector.fyers import auth as fyers_auth
from collector.fyers.auth import LOGIN_BASE_URL, TOKEN_URL, http_post, login_with_totp
from collector.fyers.errors import AuthError
from collector.fyers.secrets import FyersSecrets, load_secrets
from tests.helpers import FAKE_ENV


class FakePost:
    """Plays back Fyers' login answers in order and records every call."""

    def __init__(self, fail_first_totp: bool = False, no_auth_code: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_first_totp = fail_first_totp
        self.no_auth_code = no_auth_code
        self._totp_attempts = 0

    def __call__(self, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((url, kwargs))
        if url.endswith("send_login_otp_v2"):
            return {"request_key": "rk1"}
        if url.endswith("verify_otp"):
            self._totp_attempts += 1
            if self.fail_first_totp and self._totp_attempts == 1:
                raise AuthError("otp rejected")
            return {"request_key": "rk2"}
        if url.endswith("verify_pin_v2"):
            return {"data": {"access_token": "login-token"}}
        if url == TOKEN_URL:
            url_text = "http://x/?state=s" if self.no_auth_code else "http://x/?auth_code=CODE123"
            return {"Url": url_text}
        raise AssertionError(f"unexpected url {url}")


def _secrets() -> FyersSecrets:
    return load_secrets(FAKE_ENV)


def test_full_login_returns_exchanged_token() -> None:
    post = FakePost()
    seen: dict[str, str] = {}

    def exchange(secrets: FyersSecrets, code: str) -> str:
        seen["code"] = code
        return "final-token"

    assert login_with_totp(_secrets(), post=post, exchange=exchange, sleep=lambda s: None) == (
        "final-token"
    )
    assert seen["code"] == "CODE123"
    assert [url for url, _ in post.calls] == [
        f"{LOGIN_BASE_URL}/send_login_otp_v2",
        f"{LOGIN_BASE_URL}/verify_otp",
        f"{LOGIN_BASE_URL}/verify_pin_v2",
        TOKEN_URL,
    ]


def test_ids_and_pin_are_base64_encoded_and_client_id_is_split() -> None:
    post = FakePost()
    login_with_totp(_secrets(), post=post, exchange=lambda s, c: "t", sleep=lambda s: None)
    first = post.calls[0][1]["json"]
    assert base64.b64decode(first["fy_id"]).decode() == "XV12345"
    pin_payload = post.calls[2][1]["json"]
    assert base64.b64decode(pin_payload["identifier"]).decode() == "4321"
    token_payload = post.calls[3][1]["json"]
    assert token_payload["app_id"] == "ABCD1234E5"
    assert token_payload["appType"] == "100"
    assert post.calls[3][1]["headers"]["Authorization"] == "Bearer login-token"


def test_totp_is_retried_once_when_first_attempt_is_rejected() -> None:
    post = FakePost(fail_first_totp=True)
    pauses: list[float] = []
    login_with_totp(_secrets(), post=post, exchange=lambda s, c: "t", sleep=pauses.append)
    assert sum(url.endswith("verify_otp") for url, _ in post.calls) == 2
    assert len(pauses) == 1 and pauses[0] > 0


def test_missing_auth_code_raises_auth_error() -> None:
    post = FakePost(no_auth_code=True)
    with pytest.raises(AuthError, match="auth_code"):
        login_with_totp(_secrets(), post=post, exchange=lambda s, c: "t", sleep=lambda s: None)


def test_errors_never_contain_secrets() -> None:
    post = FakePost(no_auth_code=True)
    with pytest.raises(AuthError) as caught:
        login_with_totp(_secrets(), post=post, exchange=lambda s, c: "t", sleep=lambda s: None)
    for secret in ("XV12345", "4321", "JBSWY3DPEHPK3PXP", "supersecretvalue"):
        assert secret not in str(caught.value)


class _Response:
    def __init__(self, status: int, body: Any = None, bad_json: bool = False) -> None:
        self.status_code = status
        self._body = body
        self._bad_json = bad_json

    def json(self) -> Any:
        if self._bad_json:
            raise ValueError("not json")
        return self._body


def test_http_post_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(requests, "post", lambda url, **kw: _Response(200, {"ok": 1}))
    assert http_post("https://example.com/a") == {"ok": 1}


def test_http_post_network_error_hides_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, **kwargs: Any) -> None:
        raise requests.ConnectionError("secret-url?pin=4321")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(AuthError) as caught:
        http_post("https://example.com/a")
    assert "4321" not in str(caught.value)
    assert "ConnectionError" in str(caught.value)


def test_http_post_non_json_and_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(requests, "post", lambda url, **kw: _Response(502, bad_json=True))
    with pytest.raises(AuthError, match="non-JSON"):
        http_post("https://example.com/a")
    monkeypatch.setattr(requests, "post", lambda url, **kw: _Response(401, {"message": "bad pin"}))
    with pytest.raises(AuthError, match="401"):
        http_post("https://example.com/a")


def test_exchange_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def set_token(self, code: str) -> None:
            pass

        def generate_token(self) -> dict[str, Any]:
            return {"s": "error", "message": "invalid code"}

    from fyers_apiv3 import fyersModel

    monkeypatch.setattr(fyersModel, "SessionModel", FakeSession)
    with pytest.raises(AuthError, match="invalid code"):
        fyers_auth.exchange_auth_code(_secrets(), "CODE")


def test_exchange_success_returns_token(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def set_token(self, code: str) -> None:
            pass

        def generate_token(self) -> dict[str, Any]:
            return {"s": "ok", "access_token": "tok"}

    from fyers_apiv3 import fyersModel

    monkeypatch.setattr(fyersModel, "SessionModel", FakeSession)
    assert fyers_auth.exchange_auth_code(_secrets(), "CODE") == "tok"

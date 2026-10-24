# What: tests the browser login fallback, including a real local redirect server and its timeout.
# In: fake secrets, a free local port, and fake browser/input functions.
# Out: pass/fail results.
from __future__ import annotations

import socket
import threading
import time
import urllib.request

import pytest

from collector.fyers.auth_fallback import (
    capture_auth_code,
    login_with_browser,
    parse_auth_code,
)
from collector.fyers.errors import AuthError
from collector.fyers.secrets import FyersSecrets, load_secrets
from tests.helpers import FAKE_ENV


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_parse_full_url_and_bare_code() -> None:
    assert parse_auth_code("http://127.0.0.1:5000/?auth_code=ABC&state=x") == "ABC"
    assert parse_auth_code("  RAWCODE ") == "RAWCODE"


def test_parse_rejects_bad_input() -> None:
    with pytest.raises(AuthError):
        parse_auth_code("http://127.0.0.1:5000/?state=x")
    with pytest.raises(AuthError):
        parse_auth_code("   ")


def test_local_server_captures_auth_code() -> None:
    port = _free_port()

    def visit() -> None:
        time.sleep(0.3)
        urllib.request.urlopen(f"http://127.0.0.1:{port}/?auth_code=XYZ", timeout=5).read()

    thread = threading.Thread(target=visit)
    thread.start()
    assert capture_auth_code(f"http://127.0.0.1:{port}/", timeout_seconds=10) == "XYZ"
    thread.join()


def test_local_server_gives_up_after_timeout() -> None:
    port = _free_port()
    started = time.monotonic()
    with pytest.raises(AuthError, match="timed out"):
        capture_auth_code(f"http://127.0.0.1:{port}/", timeout_seconds=0.2)
    assert time.monotonic() - started < 5


def _secrets(redirect: str) -> FyersSecrets:
    return load_secrets({**FAKE_ENV, "redirect_uri": redirect})


def test_login_on_localhost_uses_the_local_server() -> None:
    opened: list[str] = []
    result = login_with_browser(
        _secrets("http://127.0.0.1:5000/"),
        make_url=lambda s: "https://login.example/page",
        open_browser=lambda url: opened.append(url),
        capture=lambda uri, timeout: "CAPTURED",
        exchange=lambda s, code: f"token-for-{code}",
    )
    assert result == "token-for-CAPTURED"
    assert opened == ["https://login.example/page"]


def test_login_on_other_redirect_asks_for_paste() -> None:
    result = login_with_browser(
        _secrets("https://example.com/cb"),
        make_url=lambda s: "https://login.example/page",
        open_browser=lambda url: None,
        read_input=lambda prompt: "https://example.com/cb?auth_code=PASTED",
        exchange=lambda s, code: f"token-for-{code}",
    )
    assert result == "token-for-PASTED"

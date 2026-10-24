# What: fallback Fyers login that opens the browser; you log in by hand once.
# In: FyersSecrets (from .env). Browser, input and network calls can be swapped in tests.
# Out: a fresh access token string. Raises AuthError on timeout or failure.
"""Browser (OAuth) login: the documented route, used when the automatic TOTP login breaks.

It needs a person at the browser, so it must never be started from an unattended job. The local
server waits for a limited time and then gives up instead of hanging forever.
"""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from collector.fyers.auth import ExchangeFn, exchange_auth_code
from collector.fyers.errors import AuthError
from collector.fyers.secrets import FyersSecrets

DEFAULT_TIMEOUT_SECONDS = 300
SERVER_POLL_SECONDS = 1.0
DEFAULT_HTTP_PORT = 80
LOCAL_HOSTS = ("127.0.0.1", "localhost")

OpenBrowserFn = Callable[[str], object]
ReadInputFn = Callable[[str], str]
LoginUrlFn = Callable[[FyersSecrets], str]
CaptureFn = Callable[[str, float], str]


def make_login_url(secrets: FyersSecrets) -> str:
    """Ask Fyers' SDK for the login page address."""
    from fyers_apiv3 import fyersModel

    session = fyersModel.SessionModel(
        client_id=secrets.client_id.get_secret_value(),
        secret_key=secrets.secret_key.get_secret_value(),
        redirect_uri=secrets.redirect_uri,
        response_type="code",
        grant_type="authorization_code",
    )
    return str(session.generate_authcode())


def parse_auth_code(text: str) -> str:
    """Pull the auth_code out of a pasted redirect URL, or accept a bare code."""
    text = text.strip()
    if text.startswith("http"):
        try:
            return parse_qs(urlparse(text).query)["auth_code"][0]
        except (KeyError, IndexError):
            raise AuthError("No auth_code found in the pasted URL") from None
    if not text:
        raise AuthError("Nothing was pasted")
    return text


def capture_auth_code(redirect_uri: str, timeout_seconds: float) -> str:
    """Run a one-shot local web server on the redirect address and return the auth_code it gets.

    Gives up with AuthError after timeout_seconds so an unattended run cannot hang forever.
    """
    parsed = urlparse(redirect_uri)
    found: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        """Receives the browser redirect from Fyers and stores the auth_code."""

        def do_GET(self) -> None:  # noqa: N802 - name fixed by http.server
            """Handle the redirect request."""
            params = parse_qs(urlparse(self.path).query)
            if "auth_code" in params:
                found["auth_code"] = params["auth_code"][0]
                message = "Login successful. You can close this tab."
            else:
                message = "No auth_code found in the request."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Stay silent: the request line contains the auth code."""

    server = HTTPServer((parsed.hostname or "127.0.0.1", parsed.port or DEFAULT_HTTP_PORT), Handler)
    server.timeout = SERVER_POLL_SECONDS
    deadline = time.monotonic() + timeout_seconds
    try:
        while "auth_code" not in found:
            if time.monotonic() > deadline:
                raise AuthError(f"Browser login timed out after {timeout_seconds:.0f} seconds")
            server.handle_request()
    finally:
        server.server_close()
    return found["auth_code"]


def login_with_browser(
    secrets: FyersSecrets,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    make_url: LoginUrlFn = make_login_url,
    open_browser: OpenBrowserFn = webbrowser.open,
    read_input: ReadInputFn = input,
    capture: CaptureFn = capture_auth_code,
    exchange: ExchangeFn = exchange_auth_code,
) -> str:
    """Open the Fyers login page and return an access token once you have logged in.

    A localhost redirect is caught automatically; any other redirect asks you to paste the URL.
    """
    login_url = make_url(secrets)
    open_browser(login_url)
    if urlparse(secrets.redirect_uri).hostname in LOCAL_HOSTS:
        auth_code = capture(secrets.redirect_uri, timeout_seconds)
    else:
        auth_code = parse_auth_code(
            read_input("Paste the full redirected URL (or the auth_code): ")
        )
    return exchange(secrets, auth_code)

# What: automatic Fyers login using the PIN and a generated TOTP code (no browser needed).
# In: FyersSecrets (from .env). Network calls can be swapped in tests.
# Out: a fresh access token string. Raises AuthError (safe to log) when any step fails.
"""Automatic TOTP login.

This uses Fyers' internal login endpoints (the same ones the website uses), not the documented
API, so Fyers can change them without notice. When that happens AuthError is raised and the caller
falls back to the browser login in fyers_auth_fallback.py.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import pyotp
import requests

from collector.fyers.errors import AuthError
from collector.fyers.secrets import FyersSecrets

LOGIN_BASE_URL = "https://api-t2.fyers.in/vagator/v2"
TOKEN_URL = "https://api-t1.fyers.in/api/v3/token"
REQUEST_TIMEOUT_SECONDS = 30
TOTP_WINDOW_SECONDS = 30
APP_ID_SUFFIX_LENGTH = 4  # client_id looks like "ABCD1234E5-100": app id, "-", app type
APP_TYPE_LENGTH = 3

PostFn = Callable[..., dict[str, Any]]
ExchangeFn = Callable[[FyersSecrets, str], str]
SleepFn = Callable[[float], None]


def _b64(text: str) -> str:
    """Base64-encode text, the format Fyers' login endpoints expect for id and pin."""
    return base64.b64encode(text.encode()).decode()


def http_post(url: str, **kwargs: Any) -> dict[str, Any]:
    """POST and return the JSON body; raise AuthError on a network or HTTP problem.

    Only the URL host and status are put in the error, never the request body (it holds secrets).
    """
    try:
        response = requests.post(url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    except requests.RequestException as error:
        # "from None" hides the original error: its text can contain the request URL or body.
        host = urlparse(url).netloc
        raise AuthError(f"Network error calling {host}: {type(error).__name__}") from None
    try:
        data: dict[str, Any] = response.json()
    except ValueError:
        host = urlparse(url).netloc
        raise AuthError(f"{host} returned non-JSON (HTTP {response.status_code})") from None
    if response.status_code >= 400:
        message = str(data.get("message", ""))[:200]
        raise AuthError(f"{urlparse(url).path} failed (HTTP {response.status_code}): {message}")
    return data


def exchange_auth_code(secrets: FyersSecrets, auth_code: str) -> str:
    """Swap the one-time auth code for the day's access token using Fyers' official SDK."""
    from fyers_apiv3 import fyersModel

    session = fyersModel.SessionModel(
        client_id=secrets.client_id.get_secret_value(),
        secret_key=secrets.secret_key.get_secret_value(),
        redirect_uri=secrets.redirect_uri,
        response_type="code",
        grant_type="authorization_code",
    )
    session.set_token(auth_code)
    response = session.generate_token()
    if response.get("s") != "ok":
        raise AuthError(f"Token exchange failed: {str(response.get('message', ''))[:200]}")
    return str(response["access_token"])


def _verify_totp(
    post: PostFn, sleep: SleepFn, request_key: str, totp: pyotp.TOTP
) -> dict[str, Any]:
    """Send the TOTP code; if it was rejected because the 30-second window rolled, retry once."""
    try:
        return post(
            f"{LOGIN_BASE_URL}/verify_otp", json={"request_key": request_key, "otp": totp.now()}
        )
    except AuthError:
        sleep(TOTP_WINDOW_SECONDS - (time.time() % TOTP_WINDOW_SECONDS) + 1)
        return post(
            f"{LOGIN_BASE_URL}/verify_otp", json={"request_key": request_key, "otp": totp.now()}
        )


def login_with_totp(
    secrets: FyersSecrets,
    *,
    post: PostFn = http_post,
    exchange: ExchangeFn = exchange_auth_code,
    sleep: SleepFn = time.sleep,
) -> str:
    """Run the 5-step login and return the access token.

    Steps: request OTP, verify TOTP, verify PIN, request auth code, exchange it for a token.
    """
    fyers_id = secrets.fyers_id.get_secret_value()
    client_id = secrets.client_id.get_secret_value()

    step1 = post(
        f"{LOGIN_BASE_URL}/send_login_otp_v2", json={"fy_id": _b64(fyers_id), "app_id": "2"}
    )
    totp = pyotp.TOTP(secrets.totp_key.get_secret_value())
    step2 = _verify_totp(post, sleep, step1["request_key"], totp)
    step3 = post(
        f"{LOGIN_BASE_URL}/verify_pin_v2",
        json={
            "request_key": step2["request_key"],
            "identity_type": "pin",
            "identifier": _b64(secrets.pin.get_secret_value()),
        },
    )
    login_token = step3["data"]["access_token"]
    step4 = post(
        TOKEN_URL,
        headers={"Authorization": f"Bearer {login_token}", "Content-Type": "application/json"},
        json={
            "fyers_id": fyers_id,
            "app_id": client_id[:-APP_ID_SUFFIX_LENGTH],
            "redirect_uri": secrets.redirect_uri,
            "appType": client_id[-APP_TYPE_LENGTH:],
            "code_challenge": "",
            "state": "sample_state",
            "scope": "",
            "nonce": "",
            "response_type": "code",
            "create_cookie": True,
        },
    )
    try:
        auth_code = parse_qs(urlparse(step4["Url"]).query)["auth_code"][0]
    except (KeyError, IndexError):
        raise AuthError(
            "Fyers did not return an auth_code (login endpoints may have changed)"
        ) from None
    return exchange(secrets, auth_code)

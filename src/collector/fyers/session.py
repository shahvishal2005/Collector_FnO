# What: gives the rest of the code a ready Fyers client; logs in only when the token is stale.
# In: FyersSecrets, a token file path, and whether a person is available for the browser fallback.
# Out: a logged-in FyersModel client (or an AuthError saying what to do next).
"""Session: reuse the saved token if it still works, else TOTP login, else (optionally) browser."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from collector.fyers.auth import login_with_totp
from collector.fyers.auth_fallback import login_with_browser
from collector.fyers.errors import AuthError
from collector.fyers.secrets import FyersSecrets
from collector.fyers.token_store import DEFAULT_TOKEN_PATH, load_token, save_token

log = logging.getLogger(__name__)
DEFAULT_SDK_LOG_DIR = Path("logs") / "fyers_sdk"

ValidateFn = Callable[[FyersSecrets, str], bool]
LoginFn = Callable[[FyersSecrets], str]


def build_client(
    secrets: FyersSecrets, token: str, log_dir: Path | None = DEFAULT_SDK_LOG_DIR
) -> Any:
    """Create Fyers' SDK client for a token.

    The SDK writes its own log files; without a folder it would drop them in the current
    directory (the project root), so they always go to log_dir.
    """
    from fyers_apiv3 import fyersModel

    folder = log_dir or DEFAULT_SDK_LOG_DIR
    folder.mkdir(parents=True, exist_ok=True)
    return fyersModel.FyersModel(
        client_id=secrets.client_id.get_secret_value(),
        token=token,
        is_async=False,
        log_path=str(folder),
    )


def token_is_valid(secrets: FyersSecrets, token: str) -> bool:
    """Ask Fyers for the profile; an 'ok' answer means the token still works."""
    try:
        response = build_client(secrets, token).get_profile()
    except Exception as error:  # the SDK raises many kinds of errors; any failure means "not valid"
        log.warning("token check failed: %s", type(error).__name__)
        return False
    return bool(response.get("s") == "ok")


def get_access_token(
    secrets: FyersSecrets,
    token_path: Path = DEFAULT_TOKEN_PATH,
    *,
    allow_browser: bool = False,
    validate: ValidateFn = token_is_valid,
    totp_login: LoginFn = login_with_totp,
    browser_login: LoginFn = login_with_browser,
) -> str:
    """Return a working access token, logging in only when needed.

    allow_browser must be True only when a person is at the keyboard; unattended jobs leave it
    False so a broken automatic login becomes a clear error instead of a hang.
    """
    saved = load_token(token_path)
    if saved and validate(secrets, saved):
        log.info("reusing saved access token")
        return saved
    try:
        token = totp_login(secrets)
        log.info("logged in with TOTP")
    except AuthError as error:
        log.warning("TOTP login failed: %s", error)
        if not allow_browser:
            raise AuthError(
                f"Automatic login failed ({error}). Run interactively to use the browser login."
            ) from error
        token = browser_login(secrets)
        log.info("logged in with browser fallback")
    save_token(token, token_path)
    return token

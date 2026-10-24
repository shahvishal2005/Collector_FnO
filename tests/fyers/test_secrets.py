# What: tests that secrets load only from the environment and never leak into text.
# In: fake environment dicts (the real .env is never read in tests).
# Out: pass/fail results.
from __future__ import annotations

import pytest

from collector.config.loader import ConfigError
from collector.fyers.secrets import FyersSecrets, load_secrets

FAKE_ENV = {
    "fyers_id": "XV12345",
    "client_id": "ABCD1234E5-100",
    "secret_key": "supersecretvalue",
    "redirect_uri": "http://127.0.0.1:5000/",
    "TOTP_key": "JBSWY3DPEHPK3PXP",
    "pin": "4321",
}


def test_loads_from_given_environment() -> None:
    secrets = load_secrets(FAKE_ENV)
    assert secrets.client_id.get_secret_value() == "ABCD1234E5-100"
    assert secrets.totp_key.get_secret_value() == "JBSWY3DPEHPK3PXP"


def test_secret_values_never_appear_in_repr_or_str() -> None:
    secrets = load_secrets(FAKE_ENV)
    text = repr(secrets) + str(secrets)
    for value in ("XV12345", "supersecretvalue", "JBSWY3DPEHPK3PXP", "4321", "ABCD1234E5"):
        assert value not in text


def test_missing_variables_are_named_without_values() -> None:
    env = {k: v for k, v in FAKE_ENV.items() if k not in ("pin", "TOTP_key")}
    with pytest.raises(ConfigError) as caught:
        load_secrets(env)
    message = str(caught.value)
    assert "pin" in message and "TOTP_key" in message
    assert "supersecretvalue" not in message


def test_empty_value_counts_as_missing() -> None:
    with pytest.raises(ConfigError, match="secret_key"):
        load_secrets({**FAKE_ENV, "secret_key": ""})


def test_bad_redirect_uri_is_rejected_without_leaking_values() -> None:
    with pytest.raises(ConfigError) as caught:
        load_secrets({**FAKE_ENV, "redirect_uri": "ftp://nope"})
    assert "redirect_uri" in str(caught.value)
    assert "ftp://nope" not in str(caught.value)


def test_model_is_frozen() -> None:
    secrets = load_secrets(FAKE_ENV)
    assert isinstance(secrets, FyersSecrets)
    with pytest.raises(ValueError):
        secrets.redirect_uri = "http://other"  # type: ignore[misc]

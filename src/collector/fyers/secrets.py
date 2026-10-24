# What: reads the Fyers login details from environment variables (loaded from .env).
# In: environment variables fyers_id, client_id, secret_key, redirect_uri, TOTP_key, pin.
# Out: a FyersSecrets object whose secret values are hidden when printed or logged.
"""Secrets loader: credentials come only from the environment, never from config.yaml."""

from __future__ import annotations

import os
from collections.abc import Mapping

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from collector.config.loader import ConfigError

REQUIRED_VARIABLES = ("fyers_id", "client_id", "secret_key", "redirect_uri", "TOTP_key", "pin")


class FyersSecrets(BaseModel):
    """Fyers credentials. SecretStr keeps them out of repr(), logs and error messages."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fyers_id: SecretStr
    client_id: SecretStr
    secret_key: SecretStr
    redirect_uri: str
    totp_key: SecretStr = Field(alias="TOTP_key")
    pin: SecretStr

    @field_validator("redirect_uri")
    @classmethod
    def _must_be_http_url(cls, value: str) -> str:
        """The redirect URI must be an http(s) address, since Fyers sends the auth code there."""
        if not value.startswith(("http://", "https://")):
            raise ValueError("redirect_uri must start with http:// or https://")
        return value


def load_secrets(env: Mapping[str, str] | None = None) -> FyersSecrets:
    """Build FyersSecrets from the environment; name every missing variable but never its value.

    Pass `env` in tests. When it is None, the .env file is read first and os.environ is used.
    """
    if env is None:
        load_dotenv()
        env = os.environ
    values = {name: env.get(name) for name in REQUIRED_VARIABLES}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ConfigError(f"Missing environment variables: {', '.join(missing)}")
    try:
        return FyersSecrets.model_validate(values)
    except ValidationError as error:
        # Report only the field names, never the input values, so secrets stay out of messages.
        fields = ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
        raise ConfigError(f"Invalid environment variables: {fields}") from None

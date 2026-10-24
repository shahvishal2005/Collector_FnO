# What: the error type raised by every Fyers login step.
# In: nothing.
# Out: AuthError, whose message never contains a password, pin, TOTP key or token.
"""Connection errors."""

from __future__ import annotations


class AuthError(Exception):
    """Raised when a Fyers login step fails; the message is safe to log."""

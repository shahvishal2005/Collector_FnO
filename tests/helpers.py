# What: shared test helpers: fake (non-real) Fyers credentials used by the login tests.
# In: nothing. Out: FAKE_ENV, a dictionary of made-up values.
"""Test helpers (no real network, no real credentials)."""

from __future__ import annotations

FAKE_ENV = {
    "fyers_id": "XV12345",
    "client_id": "ABCD1234E5-100",
    "secret_key": "supersecretvalue",
    "redirect_uri": "http://127.0.0.1:5000/",
    "TOTP_key": "JBSWY3DPEHPK3PXP",
    "pin": "4321",
}

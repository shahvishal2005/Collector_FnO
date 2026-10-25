# What: refuse to run the live scheduler on a computer that is not on the allowed list (the VPS).
# In: the allowed host names from the config and this computer's name. Out: True or False.
"""Host guard."""

from __future__ import annotations

import socket


def host_allowed(allowed_hosts: list[str], hostname: str | None = None) -> bool:
    """True if the list is empty (allowed anywhere) or contains this computer's name (any case)."""
    if not allowed_hosts:
        return True
    name = (hostname or socket.gethostname()).strip().lower()
    return name in {host.strip().lower() for host in allowed_hosts}

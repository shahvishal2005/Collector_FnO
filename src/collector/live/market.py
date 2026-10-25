# What: ask Fyers whether the market has traded today (so a holiday is not a trading day).
# In: a logged-in client, a spot symbol and today's date.
# Out: True (has candles today), False (none), or None (could not tell).
"""Market-open check.

The answer 'False' is only used to stop a run when it is repeated, and 'None' (any error) means
carry on: losing a real trading day is far worse than capturing a few static snapshots on a holiday.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


def market_has_traded_today(client: Any, spot_symbol: str, today: date) -> bool | None:
    """True if the 1-minute history of the spot symbol has candles dated today."""
    try:
        answer = client.history(
            data={
                "symbol": spot_symbol,
                "resolution": "1",
                "date_format": "1",
                "range_from": today.isoformat(),
                "range_to": today.isoformat(),
                "cont_flag": "1",
            }
        )
    except Exception as exc:  # the SDK raises many kinds of errors; none of them means "closed"
        log.warning("market check failed (%s); assuming open", type(exc).__name__)
        return None
    if not isinstance(answer, dict):
        return None
    candles = answer.get("candles")
    if isinstance(candles, list):
        return len(candles) > 0
    if answer.get("s") == "no_data":
        return False
    return None

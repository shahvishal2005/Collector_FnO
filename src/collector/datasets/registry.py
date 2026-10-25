# What: the four M3 datasets: participant OI, participant volume, F&O ban list, index close.
# In: nothing. Out: DATASETS, a dictionary of DailyDataset records keyed by name.
"""Registry of daily datasets (all are plain CSV text files published once per trading day)."""

from __future__ import annotations

from datetime import date

from collector.datasets.base import DailyDataset
from collector.normalise.fo_ban import BAN_SCHEMA, parse_ban_list
from collector.normalise.index_close import INDEX_CLOSE_SCHEMA, parse_index_close
from collector.normalise.participant import PARTICIPANT_SCHEMA, parse_participant
from collector.quality.daily_checks import check_ban, check_index_close, check_participant


def _ddmmyyyy(day: date) -> str:
    """NSE writes these dates as DDMMYYYY in file names."""
    return f"{day:%d%m%Y}"


DATASETS: dict[str, DailyDataset] = {
    "participant_oi": DailyDataset(
        name="participant_oi",
        description="Participant-wise open interest (Client, DII, FII, Pro)",
        kind="text",
        file_name=lambda d: f"fao_participant_oi_{_ddmmyyyy(d)}.csv",
        url=lambda base, d: f"{base.rstrip('/')}/content/nsccl/fao_participant_oi_{_ddmmyyyy(d)}.csv",
        parse=parse_participant,
        schema=PARTICIPANT_SCHEMA,
        check=check_participant,
        row_count_jump_check=False,
    ),
    "participant_volume": DailyDataset(
        name="participant_volume",
        description="Participant-wise trading volume (Client, DII, FII, Pro)",
        kind="text",
        file_name=lambda d: f"fao_participant_vol_{_ddmmyyyy(d)}.csv",
        url=lambda base, d: f"{base.rstrip('/')}/content/nsccl/fao_participant_vol_{_ddmmyyyy(d)}.csv",
        parse=parse_participant,
        schema=PARTICIPANT_SCHEMA,
        check=check_participant,
        row_count_jump_check=False,
    ),
    "fo_ban": DailyDataset(
        name="fo_ban",
        description="Securities in the F&O ban period (an empty table means nobody was banned)",
        kind="text",
        file_name=lambda d: f"fo_secban_{_ddmmyyyy(d)}.csv",
        url=lambda base, d: f"{base.rstrip('/')}/archives/fo/sec_ban/fo_secban_{_ddmmyyyy(d)}.csv",
        parse=parse_ban_list,
        schema=BAN_SCHEMA,
        check=check_ban,
        row_count_jump_check=False,
    ),
    "index_close": DailyDataset(
        name="index_close",
        description="End-of-day values of all NSE indices (OHLC, volume, P/E, P/B, yield)",
        kind="text",
        file_name=lambda d: f"ind_close_all_{_ddmmyyyy(d)}.csv",
        url=lambda base, d: f"{base.rstrip('/')}/content/indices/ind_close_all_{_ddmmyyyy(d)}.csv",
        parse=parse_index_close,
        schema=INDEX_CLOSE_SCHEMA,
        check=check_index_close,
        row_count_jump_check=True,
    ),
}

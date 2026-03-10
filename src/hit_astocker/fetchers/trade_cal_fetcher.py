"""Fetch SSE trade calendar from Tushare and store in DB."""

import logging
import sqlite3

from hit_astocker.fetchers.tushare_client import TushareClient

logger = logging.getLogger(__name__)


def sync_trade_calendar(
    client: TushareClient,
    conn: sqlite3.Connection,
    start_date: str = "20150101",
    end_date: str = "20271231",
) -> int:
    """Fetch SSE trade calendar and upsert into trade_cal table.

    Returns the number of rows written.
    """
    df = client.query(
        "trade_cal",
        exchange="SSE",
        start_date=start_date,
        end_date=end_date,
        fields="cal_date,is_open",
    )
    if df.empty:
        logger.warning("Empty trade_cal response from Tushare")
        return 0

    rows = [
        (row["cal_date"], int(row["is_open"]))
        for _, row in df.iterrows()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO trade_cal (cal_date, is_open) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    logger.info("Synced %d trade_cal rows", len(rows))
    return len(rows)

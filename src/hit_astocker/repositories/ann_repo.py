"""Repository for announcement (anns_d) data."""

import sqlite3
from collections import defaultdict
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.ann_data import AnnouncementRecord
from hit_astocker.repositories.base import BaseRepository


class AnnouncementRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "anns_d")

    def find_by_date(self, date_str: str) -> list[sqlite3.Row]:
        sql = "SELECT * FROM anns_d WHERE ann_date = ?"
        return self._conn.execute(sql, (date_str,)).fetchall()

    def find_by_codes_recent(
        self, ts_codes: list[str], trade_date: date, lookback_days: int = 3,
    ) -> dict[str, list[AnnouncementRecord]]:
        """Find recent announcements for a batch of stock codes.

        Returns {ts_code: [AnnouncementRecord, ...]} for announcements
        within lookback_days before trade_date.
        """
        if not ts_codes:
            return {}

        from hit_astocker.utils.date_utils import get_recent_trading_days

        recent = get_recent_trading_days(trade_date, lookback_days)
        all_dates = [trade_date, *recent]
        date_strs = [d.strftime(TUSHARE_DATE_FMT) for d in all_dates]

        code_ph = ",".join("?" * len(ts_codes))
        date_ph = ",".join("?" * len(date_strs))
        sql = f"""
            SELECT * FROM anns_d
            WHERE ts_code IN ({code_ph}) AND ann_date IN ({date_ph})
            ORDER BY ann_date DESC
        """
        rows = self._conn.execute(sql, [*ts_codes, *date_strs]).fetchall()

        result: dict[str, list[AnnouncementRecord]] = defaultdict(list)
        for r in rows:
            result[r["ts_code"]].append(self._to_model(r))
        return dict(result)

    @staticmethod
    def _to_model(row: sqlite3.Row) -> AnnouncementRecord:
        return AnnouncementRecord(
            ts_code=row["ts_code"] or "",
            ann_date=datetime.strptime(row["ann_date"], TUSHARE_DATE_FMT).date(),
            title=row["title"] or "",
            ann_type=row["ann_type"] or "",
            content=row["content"] or "",
        )

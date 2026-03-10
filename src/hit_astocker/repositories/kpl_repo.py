"""Repository for KPL (开盘啦) list data."""

import sqlite3
from collections import defaultdict
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.kpl_data import KplRecord
from hit_astocker.repositories.base import BaseRepository

# Shared separator used by KPL theme field: "石油石化、天然气"
THEME_SEPARATORS = ("、",)


def split_themes(raw: str) -> list[str]:
    """Split a KPL theme string into individual themes.

    The Tushare KPL data uses ``、`` as separator.
    Returns a list of stripped, non-empty theme names.
    """
    parts = [raw]
    for sep in THEME_SEPARATORS:
        new_parts: list[str] = []
        for p in parts:
            new_parts.extend(p.split(sep))
        parts = new_parts
    return [t.strip() for t in parts if t.strip()]


class KplRepository(BaseRepository):
    # ST stocks pollute theme/sector statistics — always exclude from analysis.
    # Tushare limit_list_d already excludes ST; KPL should be consistent.
    _EXCLUDE_ST = "AND name NOT LIKE '%ST%'"

    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "kpl_list")

    def find_records_by_date(self, trade_date: date) -> list[KplRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_tag(self, trade_date: date, tag: str = "涨停") -> list[KplRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = f"SELECT * FROM kpl_list WHERE trade_date = ? AND tag = ? {self._EXCLUDE_ST}"
        rows = self._conn.execute(sql, (date_str, tag)).fetchall()
        return [self._to_model(r) for r in rows]

    def get_themes_by_date(self, trade_date: date) -> dict[str, int]:
        """Get per-theme stock counts for a date (themes are split, ST excluded)."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = f"""
            SELECT theme FROM kpl_list
            WHERE trade_date = ? AND tag = '涨停' AND theme != ''
            {self._EXCLUDE_ST}
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            for t in split_themes(r["theme"]):
                counts[t] += 1
        return dict(counts)

    def get_themes_by_dates(self, trade_dates: list[date]) -> dict[str, int]:
        """Get theme day-counts across multiple dates (themes are split, ST excluded).

        Returns {theme: number_of_distinct_days_it_appeared}.
        """
        if not trade_dates:
            return {}
        date_strs = [d.strftime(TUSHARE_DATE_FMT) for d in trade_dates]
        placeholders = ",".join("?" * len(date_strs))
        sql = f"""
            SELECT trade_date, theme FROM kpl_list
            WHERE trade_date IN ({placeholders}) AND tag = '涨停' AND theme != ''
            {self._EXCLUDE_ST}
        """
        rows = self._conn.execute(sql, date_strs).fetchall()
        # theme -> set of dates it appeared
        theme_dates: dict[str, set[str]] = defaultdict(set)
        for r in rows:
            for t in split_themes(r["theme"]):
                theme_dates[t].add(r["trade_date"])
        return {t: len(dates) for t, dates in theme_dates.items()}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> KplRecord:
        return KplRecord(
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            lu_time=row["lu_time"] or "",
            ld_time=row["ld_time"] or "",
            lu_desc=row["lu_desc"] or "",
            tag=row["tag"] or "",
            theme=row["theme"] or "",
            net_change=row["net_change"] or 0.0,
            bid_amount=row["bid_amount"] or 0.0,
            status=row["status"] or "",
            pct_chg=row["pct_chg"] or 0.0,
            amount=row["amount"] or 0.0,
            turnover_rate=row["turnover_rate"] or 0.0,
            lu_limit_order=row["lu_limit_order"] or 0.0,
        )

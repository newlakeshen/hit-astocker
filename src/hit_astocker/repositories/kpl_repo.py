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
        self._tag_cache: dict[tuple[date, str], list[KplRecord]] = {}
        self._themes_cache: dict[date, dict[str, int]] = {}
        self._preloaded_range: tuple[date, date] | None = None

    def preload_range(self, start_date: date, end_date: date) -> None:
        """Bulk load kpl_list records for a date range into memory cache."""
        from collections import defaultdict as _ddict

        start_str = start_date.strftime(TUSHARE_DATE_FMT)
        end_str = end_date.strftime(TUSHARE_DATE_FMT)
        sql = (
            f"SELECT * FROM kpl_list "
            f"WHERE trade_date >= ? AND trade_date <= ? {self._EXCLUDE_ST} "
            f"ORDER BY trade_date, ts_code"
        )
        rows = self._conn.execute(sql, (start_str, end_str)).fetchall()
        by_date_tag: dict[tuple[date, str], list[KplRecord]] = _ddict(list)
        for row in rows:
            rec = self._to_model(row)
            by_date_tag[(rec.trade_date, rec.tag)].append(rec)
        self._tag_cache.update(by_date_tag)
        self._preloaded_range = (start_date, end_date)

    def _in_preloaded_range(self, trade_date: date) -> bool:
        if self._preloaded_range is None:
            return False
        return self._preloaded_range[0] <= trade_date <= self._preloaded_range[1]

    def find_records_by_date(self, trade_date: date) -> list[KplRecord]:
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        return [self._to_model(r) for r in rows]

    def find_by_tag(self, trade_date: date, tag: str = "涨停") -> list[KplRecord]:
        cache_key = (trade_date, tag)
        if cache_key in self._tag_cache:
            return self._tag_cache[cache_key]
        if self._in_preloaded_range(trade_date):
            return []
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = f"SELECT * FROM kpl_list WHERE trade_date = ? AND tag = ? {self._EXCLUDE_ST}"
        rows = self._conn.execute(sql, (date_str, tag)).fetchall()
        records = [self._to_model(r) for r in rows]
        self._tag_cache[cache_key] = records
        return records

    def get_themes_by_date(self, trade_date: date) -> dict[str, int]:
        """Get per-theme stock counts for a date (themes are split, ST excluded)."""
        if trade_date in self._themes_cache:
            return self._themes_cache[trade_date]
        # Try to derive from tag cache if available
        cache_key = (trade_date, "涨停")
        if cache_key in self._tag_cache or self._in_preloaded_range(trade_date):
            records = self.find_by_tag(trade_date, "涨停")
            counts: dict[str, int] = defaultdict(int)
            for rec in records:
                if rec.theme:
                    for t in split_themes(rec.theme):
                        counts[t] += 1
            result = dict(counts)
            self._themes_cache[trade_date] = result
            return result
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = f"""
            SELECT theme FROM kpl_list
            WHERE trade_date = ? AND tag = '涨停' AND theme != ''
            {self._EXCLUDE_ST}
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        counts = defaultdict(int)
        for r in rows:
            for t in split_themes(r["theme"]):
                counts[t] += 1
        result = dict(counts)
        self._themes_cache[trade_date] = result
        return result

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

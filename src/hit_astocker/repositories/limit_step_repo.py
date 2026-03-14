"""Repository for limit_step (consecutive board ladder) data.

Supports optional per-date caching and bulk preloading for training performance.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.limit_step import ConsecutiveLimitRecord
from hit_astocker.repositories.base import BaseRepository


class LimitStepRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "limit_step")
        self._records_cache: dict[date, list[ConsecutiveLimitRecord]] = {}
        self._preloaded_range: tuple[date, date] | None = None

    # ── Bulk preload ─────────────────────────────────────────────

    def preload_range(self, start_date: date, end_date: date) -> None:
        """Bulk load all records for *[start_date, end_date]* into memory."""
        start_str = start_date.strftime(TUSHARE_DATE_FMT)
        end_str = end_date.strftime(TUSHARE_DATE_FMT)
        sql = (
            "SELECT * FROM limit_step "
            "WHERE trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date, nums DESC"
        )
        rows = self._conn.execute(sql, (start_str, end_str)).fetchall()
        by_date: dict[date, list[ConsecutiveLimitRecord]] = defaultdict(list)
        for row in rows:
            record = self._to_model(row)
            by_date[record.trade_date].append(record)
        self._records_cache.update(by_date)
        self._preloaded_range = (start_date, end_date)

    def _in_preloaded_range(self, trade_date: date) -> bool:
        if self._preloaded_range is None:
            return False
        return self._preloaded_range[0] <= trade_date <= self._preloaded_range[1]

    # ── Core query (with cache) ──────────────────────────────────

    def find_records_by_date(self, trade_date: date) -> list[ConsecutiveLimitRecord]:
        if trade_date in self._records_cache:
            return self._records_cache[trade_date]
        if self._in_preloaded_range(trade_date):
            return []
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        records = [self._to_model(r) for r in rows]
        self._records_cache[trade_date] = records
        return records

    # ── Derived queries (cache-aware) ────────────────────────────

    def find_by_height(self, trade_date: date, min_height: int = 2) -> list[ConsecutiveLimitRecord]:
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            return [
                r for r in self.find_records_by_date(trade_date)
                if r.nums >= min_height
            ]
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT * FROM limit_step WHERE trade_date = ? AND nums >= ? ORDER BY nums DESC"
        rows = self._conn.execute(sql, (date_str, min_height)).fetchall()
        return [self._to_model(r) for r in rows]

    def get_max_height(self, trade_date: date) -> int:
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            records = self.find_records_by_date(trade_date)
            return max((r.nums for r in records), default=0)
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT MAX(nums) FROM limit_step WHERE trade_date = ?"
        row = self._conn.execute(sql, (date_str,)).fetchone()
        return row[0] if row[0] is not None else 0

    def get_height_counts(self, trade_date: date) -> dict[int, int]:
        """Get count of stocks at each consecutive board height."""
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            counts: dict[int, int] = defaultdict(int)
            for r in self.find_records_by_date(trade_date):
                counts[r.nums] += 1
            return dict(counts)
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT nums, COUNT(*) as cnt
            FROM limit_step WHERE trade_date = ?
            GROUP BY nums ORDER BY nums DESC
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["nums"]: r["cnt"] for r in rows}

    def get_stock_heights(self, trade_date: date) -> dict[str, int]:
        """Get {ts_code: height} mapping for a date."""
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            return {r.ts_code: r.nums for r in self.find_records_by_date(trade_date)}
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = "SELECT ts_code, nums FROM limit_step WHERE trade_date = ?"
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["ts_code"]: r["nums"] for r in rows}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> ConsecutiveLimitRecord:
        return ConsecutiveLimitRecord(
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            nums=row["nums"] or 0,
        )

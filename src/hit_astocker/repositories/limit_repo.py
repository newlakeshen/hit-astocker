"""Repository for limit_list_d data.

Supports optional per-date caching and bulk preloading for training performance.
When ``preload_range()`` is called, all subsequent per-date queries use in-memory
data instead of individual SQL queries.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, datetime

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.limit_data import LimitDirection, LimitRecord
from hit_astocker.repositories.base import BaseRepository


class LimitListRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "limit_list_d")
        self._records_cache: dict[date, list[LimitRecord]] = {}
        self._preloaded_range: tuple[date, date] | None = None

    # ── Bulk preload ─────────────────────────────────────────────

    def preload_range(self, start_date: date, end_date: date) -> None:
        """Bulk load all records for *[start_date, end_date]* into memory.

        After preloading, per-date queries within the range use in-memory data
        and skip SQL entirely. Saves thousands of queries during training.
        """
        start_str = start_date.strftime(TUSHARE_DATE_FMT)
        end_str = end_date.strftime(TUSHARE_DATE_FMT)
        sql = (
            "SELECT * FROM limit_list_d "
            "WHERE trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date, ts_code"
        )
        rows = self._conn.execute(sql, (start_str, end_str)).fetchall()
        by_date: dict[date, list[LimitRecord]] = defaultdict(list)
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

    def find_records_by_date(self, trade_date: date) -> list[LimitRecord]:
        if trade_date in self._records_cache:
            return self._records_cache[trade_date]
        if self._in_preloaded_range(trade_date):
            return []  # preloaded range has no data for this date
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        rows = self.find_by_date(date_str)
        records = [self._to_model(r) for r in rows]
        self._records_cache[trade_date] = records
        return records

    def find_records_by_type(
        self, trade_date: date, limit_type: LimitDirection,
    ) -> list[LimitRecord]:
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            return [
                r for r in self.find_records_by_date(trade_date)
                if r.limit == limit_type
            ]
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = 'SELECT * FROM limit_list_d WHERE trade_date = ? AND "limit" = ?'
        rows = self._conn.execute(sql, (date_str, limit_type.value)).fetchall()
        return [self._to_model(r) for r in rows]

    # ── Derived queries (cache-aware) ────────────────────────────

    def count_by_type(self, trade_date: date) -> dict[str, int]:
        """Count limit-up, limit-down, broken for a date."""
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            result = {"U": 0, "D": 0, "Z": 0}
            for r in self.find_records_by_date(trade_date):
                if r.limit.value in result:
                    result[r.limit.value] += 1
            return result
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT "limit", COUNT(*) as cnt
            FROM limit_list_d
            WHERE trade_date = ?
            GROUP BY "limit"
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        result = {"U": 0, "D": 0, "Z": 0}
        for r in rows:
            result[r["limit"]] = r["cnt"]
        return result

    def find_first_board_stocks(self, trade_date: date) -> list[LimitRecord]:
        """Find stocks with their first limit-up (limit_times == 1)."""
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            return sorted(
                [
                    r for r in self.find_records_by_date(trade_date)
                    if r.limit == LimitDirection.UP and r.limit_times == 1
                ],
                key=lambda r: r.first_time,
            )
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT * FROM limit_list_d
            WHERE trade_date = ? AND "limit" = 'U' AND limit_times = 1
            ORDER BY first_time ASC
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return [self._to_model(r) for r in rows]

    def count_yizi(self, trade_date: date) -> int:
        """Count 一字板 (opened at limit-up, never broke)."""
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            return sum(
                1 for r in self.find_records_by_date(trade_date)
                if r.limit == LimitDirection.UP and r.open_times == 0
            )
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT COUNT(*) FROM limit_list_d
            WHERE trade_date = ? AND "limit" = 'U' AND open_times = 0
        """
        row = self._conn.execute(sql, (date_str,)).fetchone()
        return row[0] if row else 0

    def count_recovery(self, trade_date: date) -> tuple[int, int]:
        """Count (回封数, 炸板数).

        回封 = limit='U' AND open_times > 0 (broke but recovered).
        炸板 = limit='Z' (broke and stayed broken).
        Returns (recovery_count, broken_count).
        """
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            records = self.find_records_by_date(trade_date)
            recovery = sum(
                1 for r in records
                if r.limit == LimitDirection.UP and r.open_times > 0
            )
            broken = sum(
                1 for r in records if r.limit == LimitDirection.BROKEN
            )
            return (recovery, broken)
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT
                SUM(CASE WHEN "limit" = 'U' AND open_times > 0 THEN 1 ELSE 0 END) as recovery,
                SUM(CASE WHEN "limit" = 'Z' THEN 1 ELSE 0 END) as broken
            FROM limit_list_d WHERE trade_date = ?
        """
        row = self._conn.execute(sql, (date_str,)).fetchone()
        return (row["recovery"] or 0, row["broken"] or 0)

    def count_by_board_type(self, trade_date: date) -> dict[str, int]:
        """Count limit-up by board type: 10cm (主板 00/60) vs 20cm (创/科 30/68).

        Returns {'10cm_up': N, '20cm_up': N, '10cm_broken': N, '20cm_broken': N}.
        """
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            result = {"10cm_up": 0, "20cm_up": 0, "10cm_broken": 0, "20cm_broken": 0}
            for r in self.find_records_by_date(trade_date):
                is_20cm = r.ts_code[:2] in ("30", "68")
                if r.limit == LimitDirection.UP:
                    result["20cm_up" if is_20cm else "10cm_up"] += 1
                elif r.limit == LimitDirection.BROKEN:
                    result["20cm_broken" if is_20cm else "10cm_broken"] += 1
            return result
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT
                "limit",
                SUM(CASE WHEN ts_code LIKE '00%' OR ts_code LIKE '60%' THEN 1 ELSE 0 END) as cnt_10,
                SUM(CASE WHEN ts_code LIKE '30%' OR ts_code LIKE '68%' THEN 1 ELSE 0 END) as cnt_20
            FROM limit_list_d
            WHERE trade_date = ? AND "limit" IN ('U', 'Z')
            GROUP BY "limit"
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        result = {"10cm_up": 0, "20cm_up": 0, "10cm_broken": 0, "20cm_broken": 0}
        for r in rows:
            if r["limit"] == "U":
                result["10cm_up"] = r["cnt_10"] or 0
                result["20cm_up"] = r["cnt_20"] or 0
            elif r["limit"] == "Z":
                result["10cm_broken"] = r["cnt_10"] or 0
                result["20cm_broken"] = r["cnt_20"] or 0
        return result

    def get_prev_limit_up_closes(self, trade_date: date) -> dict[str, float]:
        """Get {ts_code: close_price} for previous day's limit-up stocks."""
        if trade_date in self._records_cache or self._in_preloaded_range(trade_date):
            return {
                r.ts_code: r.close
                for r in self.find_records_by_date(trade_date)
                if r.limit == LimitDirection.UP and r.close > 0
            }
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT ts_code, "close" FROM limit_list_d
            WHERE trade_date = ? AND "limit" = 'U'
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return {r["ts_code"]: r["close"] for r in rows if r["close"]}

    @staticmethod
    def _to_model(row: sqlite3.Row) -> LimitRecord:
        return LimitRecord(
            trade_date=datetime.strptime(row["trade_date"], TUSHARE_DATE_FMT).date(),
            ts_code=row["ts_code"] or "",
            name=row["name"] or "",
            industry=row["industry"] or "",
            close=row["close"] or 0.0,
            pct_chg=row["pct_chg"] or 0.0,
            amount=row["amount"] or 0.0,
            limit_amount=row["limit_amount"] or 0.0,
            float_mv=row["float_mv"] or 0.0,
            total_mv=row["total_mv"] or 0.0,
            turnover_ratio=row["turnover_ratio"] or 0.0,
            fd_amount=row["fd_amount"] or 0.0,
            first_time=row["first_time"] or "",
            last_time=row["last_time"] or "",
            open_times=row["open_times"] or 0,
            up_stat=row["up_stat"] or "",
            limit_times=row["limit_times"] or 0,
            limit=LimitDirection(row["limit"]),
        )

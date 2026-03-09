"""Base repository with common query patterns."""

import sqlite3
from typing import Any


class BaseRepository:
    def __init__(self, conn: sqlite3.Connection, table_name: str):
        self._conn = conn
        self._table = table_name

    def upsert_many(self, records: list[dict[str, Any]]) -> int:
        """Insert or replace many records. Returns count inserted."""
        if not records:
            return 0
        columns = list(records[0].keys())
        placeholders = ", ".join(["?"] * len(columns))
        col_names = ", ".join(f'"{c}"' for c in columns)
        sql = f"INSERT OR REPLACE INTO {self._table} ({col_names}) VALUES ({placeholders})"
        values = [tuple(r[c] for c in columns) for r in records]
        self._conn.executemany(sql, values)
        return len(values)

    def find_by_date(self, trade_date: str) -> list[sqlite3.Row]:
        """Find all records for a given trade date."""
        sql = f"SELECT * FROM {self._table} WHERE trade_date = ?"
        return self._conn.execute(sql, (trade_date,)).fetchall()

    def find_by_date_range(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        """Find records in date range (inclusive)."""
        sql = f"SELECT * FROM {self._table} WHERE trade_date >= ? AND trade_date <= ? ORDER BY trade_date"
        return self._conn.execute(sql, (start_date, end_date)).fetchall()

    def find_by_code_and_date(self, ts_code: str, trade_date: str) -> list[sqlite3.Row]:
        """Find records for a specific stock on a specific date."""
        sql = f"SELECT * FROM {self._table} WHERE ts_code = ? AND trade_date = ?"
        return self._conn.execute(sql, (ts_code, trade_date)).fetchall()

    def count_by_date(self, trade_date: str) -> int:
        """Count records for a given date."""
        sql = f"SELECT COUNT(*) FROM {self._table} WHERE trade_date = ?"
        row = self._conn.execute(sql, (trade_date,)).fetchone()
        return row[0] if row else 0

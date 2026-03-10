"""Repository for concept_detail and ths_member data."""

import sqlite3
from collections import defaultdict

from hit_astocker.repositories.base import BaseRepository


class ConceptRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "concept_detail")

    def find_concepts_for_codes(
        self, ts_codes: list[str],
    ) -> dict[str, list[str]]:
        """Find concept names for a batch of stock codes.

        Returns {ts_code: [concept_name, ...]}.
        Only returns active memberships (out_date is empty).
        """
        if not ts_codes:
            return {}
        placeholders = ",".join("?" * len(ts_codes))
        sql = f"""
            SELECT ts_code, concept_name FROM concept_detail
            WHERE ts_code IN ({placeholders})
              AND (out_date IS NULL OR out_date = '')
        """
        rows = self._conn.execute(sql, ts_codes).fetchall()
        result: dict[str, list[str]] = defaultdict(list)
        for r in rows:
            result[r["ts_code"]].append(r["concept_name"])
        return dict(result)

    def get_concept_members(self, concept_name: str) -> list[str]:
        """Get all active stock codes in a concept."""
        sql = """
            SELECT ts_code FROM concept_detail
            WHERE concept_name = ?
              AND (out_date IS NULL OR out_date = '')
        """
        rows = self._conn.execute(sql, (concept_name,)).fetchall()
        return [r["ts_code"] for r in rows]

    def has_data(self) -> bool:
        """Check if concept_detail has any data."""
        row = self._conn.execute("SELECT COUNT(*) FROM concept_detail").fetchone()
        return row[0] > 0 if row else False


class ThsMemberRepository(BaseRepository):
    def __init__(self, conn: sqlite3.Connection):
        super().__init__(conn, "ths_member")

    def find_concepts_for_code(self, stock_code: str) -> list[str]:
        """Find THS concept codes that include this stock."""
        sql = """
            SELECT DISTINCT ts_code FROM ths_member
            WHERE code = ?
              AND (out_date IS NULL OR out_date = '')
        """
        rows = self._conn.execute(sql, (stock_code,)).fetchall()
        return [r["ts_code"] for r in rows]

    def get_member_count(self, concept_code: str) -> int:
        """Count active members in a THS concept."""
        sql = """
            SELECT COUNT(*) FROM ths_member
            WHERE ts_code = ?
              AND (out_date IS NULL OR out_date = '')
        """
        row = self._conn.execute(sql, (concept_code,)).fetchone()
        return row[0] if row else 0

    def find_members_batch(
        self, concept_codes: list[str],
    ) -> dict[str, list[str]]:
        """Find member stock codes for multiple concepts.

        Returns {concept_code: [stock_code, ...]}.
        """
        if not concept_codes:
            return {}
        placeholders = ",".join("?" * len(concept_codes))
        sql = f"""
            SELECT ts_code, code FROM ths_member
            WHERE ts_code IN ({placeholders})
              AND (out_date IS NULL OR out_date = '')
        """
        rows = self._conn.execute(sql, concept_codes).fetchall()
        result: dict[str, list[str]] = defaultdict(list)
        for r in rows:
            result[r["ts_code"]].append(r["code"])
        return dict(result)

    def has_data(self) -> bool:
        row = self._conn.execute("SELECT COUNT(*) FROM ths_member").fetchone()
        return row[0] > 0 if row else False

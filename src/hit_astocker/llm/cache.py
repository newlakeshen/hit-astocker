"""SQLite-based LLM response cache with TTL."""

import hashlib
import json
import logging
import sqlite3
import time

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""

_DEFAULT_TTL = 86400  # 24 hours


class LLMCache:
    """SQLite cache for LLM responses, keyed by SHA256(date+type+content)."""

    def __init__(self, conn: sqlite3.Connection, ttl: float = _DEFAULT_TTL):
        self._conn = conn
        self._ttl = ttl
        self._ensure_table()

    def _ensure_table(self) -> None:
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    @staticmethod
    def make_key(trade_date: str, call_type: str, content: str) -> str:
        """Generate a deterministic cache key."""
        raw = f"{trade_date}|{call_type}|{content}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> str | None:
        """Retrieve cached response if not expired."""
        row = self._conn.execute(
            "SELECT response, created_at FROM llm_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        if time.time() - row[1] > self._ttl:
            self._conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (key,))
            self._conn.commit()
            return None
        return row[0]

    def put(self, key: str, response: str) -> None:
        """Store response in cache."""
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, response, created_at) "
            "VALUES (?, ?, ?)",
            (key, response, time.time()),
        )
        self._conn.commit()

    def get_json(self, key: str) -> list | dict | None:
        """Get cached response and parse as JSON."""
        raw = self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Cache JSON decode failed for key %s", key[:16])
            return None

    def put_json(self, key: str, data: list | dict) -> None:
        """Serialize data as JSON and cache it."""
        self.put(key, json.dumps(data, ensure_ascii=False))

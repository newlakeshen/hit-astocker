"""Simple schema version tracking."""

import sqlite3

from hit_astocker.database.schema import init_schema

CURRENT_VERSION = 9

# v6: ths_hot 补齐 data_type / current_price / rank_reason / rank_time
_V6_ALTER_THS_HOT = [
    "ALTER TABLE ths_hot ADD COLUMN data_type TEXT DEFAULT ''",
    "ALTER TABLE ths_hot ADD COLUMN current_price REAL DEFAULT 0",
    "ALTER TABLE ths_hot ADD COLUMN rank_reason TEXT DEFAULT ''",
    "ALTER TABLE ths_hot ADD COLUMN rank_time TEXT DEFAULT ''",
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure database schema is up to date."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _schema_version (
            version INTEGER NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    row = conn.execute("SELECT MAX(version) FROM _schema_version").fetchone()
    current = row[0] if row[0] is not None else 0

    if current < CURRENT_VERSION:
        init_schema(conn)

        # v6: add missing columns to existing ths_hot tables
        if current < 6:
            for sql in _V6_ALTER_THS_HOT:
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass  # column already exists (fresh DB)

        conn.execute(
            "INSERT INTO _schema_version (version) VALUES (?)",
            (CURRENT_VERSION,),
        )
        conn.commit()

    # Always initialise the trade calendar singleton from DB
    from hit_astocker.utils.trade_calendar import init_trade_calendar
    init_trade_calendar(conn)

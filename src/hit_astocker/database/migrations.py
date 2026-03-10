"""Simple schema version tracking."""

import sqlite3

from hit_astocker.database.schema import init_schema

CURRENT_VERSION = 5


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
        conn.execute(
            "INSERT INTO _schema_version (version) VALUES (?)",
            (CURRENT_VERSION,),
        )
        conn.commit()

    # Always initialise the trade calendar singleton from DB
    from hit_astocker.utils.trade_calendar import init_trade_calendar
    init_trade_calendar(conn)

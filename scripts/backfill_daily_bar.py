"""Backfill missing daily_bar data one day at a time.

Usage: python scripts/backfill_daily_bar.py

Key fix: use page_size=5000 so each date needs only 1 API call
(not 94 calls at default batch_size=50).
"""

import sqlite3
import sys
import time
from datetime import date

from hit_astocker.config.settings import Settings
from hit_astocker.fetchers.tushare_client import TushareClient
from hit_astocker.repositories.base import BaseRepository


FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"


def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def fetch_daily_bar(client: TushareClient, date_str: str) -> list[dict]:
    """Fetch daily_bar for one date with page_size=5000 (single page)."""
    for attempt in range(3):
        try:
            df = client.query(
                "daily",
                trade_date=date_str,
                fields=FIELDS,
                page_size=5000,
            )
            if df.empty:
                return []
            records = []
            for _, row in df.iterrows():
                records.append({
                    "trade_date": row.get("trade_date", ""),
                    "ts_code": row.get("ts_code", ""),
                    "open": _safe_float(row.get("open")),
                    "high": _safe_float(row.get("high")),
                    "low": _safe_float(row.get("low")),
                    "close": _safe_float(row.get("close")),
                    "pre_close": _safe_float(row.get("pre_close")),
                    "change": _safe_float(row.get("change")),
                    "pct_chg": _safe_float(row.get("pct_chg")),
                    "vol": _safe_float(row.get("vol")),
                    "amount": _safe_float(row.get("amount")),
                })
            return records
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                raise


def main() -> None:
    settings = Settings()
    client = TushareClient(settings.tushare_token)
    conn = sqlite3.connect("data/hit_astocker.db")

    # Find missing trading dates
    missing = [
        r[0]
        for r in conn.execute(
            """
        SELECT c.cal_date
        FROM trade_cal c
        LEFT JOIN (SELECT DISTINCT trade_date FROM daily_bar) d
            ON c.cal_date = d.trade_date
        WHERE c.is_open = 1
          AND c.cal_date >= '20200102' AND c.cal_date <= '20260312'
          AND d.trade_date IS NULL
        ORDER BY c.cal_date
        """
        ).fetchall()
    ]

    total = len(missing)
    if total == 0:
        print("No missing dates. daily_bar is complete.")
        return

    print(f"Backfilling {total} dates (page_size=5000, ~1s/call)...")
    sys.stdout.flush()

    repo = BaseRepository(conn, "daily_bar")
    done = 0
    errors = 0
    total_rows = 0
    start_time = time.time()

    for date_str in missing:
        try:
            records = fetch_daily_bar(client, date_str)
            if records:
                repo.upsert_many(records)
                total_rows += len(records)
            done += 1

            if done % 10 == 0:
                conn.commit()
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate / 60 if rate > 0 else 0
                print(
                    f"  [{done}/{total}] {done/total*100:.0f}% — "
                    f"{date_str} — {total_rows:,} rows — "
                    f"ETA {eta:.0f}min"
                )
                sys.stdout.flush()

            # Rate limit: stay under 200/min
            time.sleep(0.5)

        except Exception as e:
            errors += 1
            print(f"  ERROR {date_str}: {e}", file=sys.stderr)
            sys.stderr.flush()
            time.sleep(5)

    conn.commit()
    conn.close()
    elapsed = time.time() - start_time
    print(
        f"\nDone: {done} success, {errors} errors, "
        f"{total_rows:,} rows in {elapsed/60:.1f} minutes"
    )


if __name__ == "__main__":
    main()

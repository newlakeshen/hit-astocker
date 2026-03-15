"""Fetcher for daily bar (K-line) data."""

import logging

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

logger = logging.getLogger(__name__)

FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"


class DailyBarFetcher(FetcherBase):
    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query("daily", trade_date=date_str, fields=FIELDS)

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "daily",
            start_date=start_str,
            end_date=end_str,
            fields=FIELDS,
            page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            close = _safe_float(row.get("close"))
            if close <= 0:
                logger.warning(
                    "Skipping invalid daily_bar: close=%.2f for %s on %s",
                    close,
                    row.get("ts_code", ""),
                    row.get("trade_date", ""),
                )
                continue
            high = _safe_float(row.get("high"))
            low = _safe_float(row.get("low"))
            if high > 0 and low > 0 and high < low:
                logger.warning(
                    "Suspicious OHLC: high=%.2f < low=%.2f for %s on %s",
                    high,
                    low,
                    row.get("ts_code", ""),
                    row.get("trade_date", ""),
                )
            records.append(
                {
                    "trade_date": row.get("trade_date", ""),
                    "ts_code": row.get("ts_code", ""),
                    "open": _safe_float(row.get("open")),
                    "high": high,
                    "low": low,
                    "close": close,
                    "pre_close": _safe_float(row.get("pre_close")),
                    "change": _safe_float(row.get("change")),
                    "pct_chg": _safe_float(row.get("pct_chg")),
                    "vol": _safe_float(row.get("vol")),
                    "amount": _safe_float(row.get("amount")),
                }
            )
        return records

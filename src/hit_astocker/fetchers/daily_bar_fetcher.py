"""Fetcher for daily bar (K-line) data."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"


class DailyBarFetcher(FetcherBase):
    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query("daily", trade_date=date_str, fields=FIELDS)

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "daily", start_date=start_str, end_date=end_str,
            fields=FIELDS, page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
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

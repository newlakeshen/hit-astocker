"""Fetcher for limit_step API (consecutive board ladder)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_int


class StepFetcher(FetcherBase):
    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "limit_step", trade_date=date_str,
            fields="ts_code,name,trade_date,nums",
        )

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "limit_step", start_date=start_str, end_date=end_str,
            fields="ts_code,name,trade_date,nums", page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", ""),
                "nums": _safe_int(row.get("nums")),
            })
        return records

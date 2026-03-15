"""Fetcher for ths_hot API (同花顺热股排名)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float, _safe_int

FIELDS = (
    "trade_date,ts_code,ts_name,data_type,current_price,"
    "rank,pct_change,rank_reason,rank_time,concept,hot,market"
)


class ThsHotFetcher(FetcherBase):
    def __init__(self, client, *, market: str = "热股"):
        super().__init__(client)
        self._market = market

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "ths_hot",
            trade_date=date_str,
            market=self._market,
            fields=FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "trade_date": row.get("trade_date", ""),
                    "ts_code": row.get("ts_code", ""),
                    "ts_name": row.get("ts_name", "") or "",
                    "data_type": row.get("data_type", "") or "",
                    "current_price": _safe_float(row.get("current_price")),
                    "rank": _safe_int(row.get("rank")),
                    "pct_change": _safe_float(row.get("pct_change")),
                    "rank_reason": row.get("rank_reason", "") or "",
                    "rank_time": row.get("rank_time", "") or "",
                    "concept": row.get("concept", "") or "",
                    "hot": _safe_int(row.get("hot")),
                    "market": row.get("market", "") or self._market,
                }
            )
        return records

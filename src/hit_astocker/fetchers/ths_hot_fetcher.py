"""Fetcher for ths_hot API (同花顺热股排名)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

FIELDS = "trade_date,ts_code,ts_name,rank,pct_change,concept,hot,market"


class ThsHotFetcher(FetcherBase):
    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "ths_hot",
            trade_date=date_str,
            market="热股",
            fields=FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "ts_name": row.get("ts_name", "") or "",
                "rank": int(row.get("rank", 0) or 0),
                "pct_change": _safe_float(row.get("pct_change")),
                "concept": row.get("concept", "") or "",
                "hot": int(row.get("hot", 0) or 0),
                "market": row.get("market", "") or "热股",
            })
        return records

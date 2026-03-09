"""Fetcher for hsgt_top10 API (北向资金十大成交股)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

FIELDS = "trade_date,ts_code,name,close,change,rank,market_type,amount,net_amount,buy,sell"


class HsgtTop10Fetcher(FetcherBase):
    """Fetch northbound capital top 10 stocks (沪股通 + 深股通)."""

    def _call_api(self, date_str: str) -> pd.DataFrame:
        # Fetch both SH and SZ northbound data
        frames = []
        for market_type in ("1", "3"):  # 1=沪股通, 3=深股通
            df = self._client.query(
                "hsgt_top10",
                trade_date=date_str,
                market_type=market_type,
                fields=FIELDS,
            )
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", "") or "",
                "close": _safe_float(row.get("close")),
                "change": _safe_float(row.get("change")),
                "rank": int(row.get("rank", 0) or 0),
                "market_type": row.get("market_type", "") or "",
                "amount": _safe_float(row.get("amount")),
                "net_amount": _safe_float(row.get("net_amount")),
                "buy": _safe_float(row.get("buy")),
                "sell": _safe_float(row.get("sell")),
            })
        return records

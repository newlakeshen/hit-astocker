"""Fetcher for market index daily data (指数日线)."""

import logging

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

logger = logging.getLogger(__name__)

# 上证综指 + 创业板指 + 深证成指
INDEX_CODES = "000001.SH,399006.SZ,399001.SZ"
FIELDS = "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount"


class IndexDailyFetcher(FetcherBase):
    def _call_api(self, date_str: str) -> pd.DataFrame:
        # index_daily requires ts_code; fetch each index separately and concat
        frames = []
        for code in INDEX_CODES.split(","):
            df = self._client.query(
                "index_daily",
                ts_code=code,
                trade_date=date_str,
                fields=FIELDS,
            )
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        frames = []
        for code in INDEX_CODES.split(","):
            df = self._client.query(
                "index_daily",
                ts_code=code,
                start_date=start_str,
                end_date=end_str,
                fields=FIELDS,
                page_size=5000,
            )
            if not df.empty:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            close = _safe_float(row.get("close"))
            if close <= 0:
                logger.warning(
                    "Skipping invalid index_daily: close=%.2f for %s on %s",
                    close,
                    row.get("ts_code", ""),
                    row.get("trade_date", ""),
                )
                continue
            records.append(
                {
                    "trade_date": row.get("trade_date", ""),
                    "ts_code": row.get("ts_code", ""),
                    "open": _safe_float(row.get("open")),
                    "high": _safe_float(row.get("high")),
                    "low": _safe_float(row.get("low")),
                    "close": close,
                    "pre_close": _safe_float(row.get("pre_close")),
                    "pct_chg": _safe_float(row.get("pct_chg")),
                    "vol": _safe_float(row.get("vol")),
                    "amount": _safe_float(row.get("amount")),
                }
            )
        return records

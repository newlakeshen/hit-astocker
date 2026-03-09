"""Fetcher for stk_factor_pro API (个股技术因子)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

FIELDS = (
    "ts_code,trade_date,close,"
    "macd_dif,macd_dea,macd,"
    "kdj_k,kdj_d,kdj_j,"
    "rsi_6,rsi_12,"
    "boll_upper,boll_mid,boll_lower"
)


class StockFactorFetcher(FetcherBase):
    """Fetch daily technical factors for limit-up candidates.

    Note: stk_factor_pro requires ts_code parameter (per-stock),
    so we batch fetch for a list of candidate codes.
    """

    def __init__(self, client, rate_limiter, ts_codes: list[str] | None = None):
        super().__init__(client, rate_limiter)
        self._ts_codes = ts_codes or []

    def fetch_for_codes(self, date_str: str, ts_codes: list[str]) -> list[dict]:
        """Fetch factors for a specific list of stock codes."""
        all_records = []
        for code in ts_codes:
            try:
                self._limiter.acquire()
                df = self._client.query(
                    "stk_factor_pro",
                    ts_code=code,
                    trade_date=date_str,
                    fields=FIELDS,
                )
                if not df.empty:
                    all_records.extend(self._transform(df))
            except Exception:
                continue  # Skip individual failures
        return all_records

    def _call_api(self, date_str: str) -> pd.DataFrame:
        # For orchestrator-based sync, fetch for pre-configured codes
        if not self._ts_codes:
            return pd.DataFrame()
        frames = []
        for code in self._ts_codes:
            df = self._client.query(
                "stk_factor_pro",
                ts_code=code,
                trade_date=date_str,
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
                "close": _safe_float(row.get("close")),
                "macd_dif": _safe_float(row.get("macd_dif")),
                "macd_dea": _safe_float(row.get("macd_dea")),
                "macd": _safe_float(row.get("macd")),
                "kdj_k": _safe_float(row.get("kdj_k")),
                "kdj_d": _safe_float(row.get("kdj_d")),
                "kdj_j": _safe_float(row.get("kdj_j")),
                "rsi_6": _safe_float(row.get("rsi_6")),
                "rsi_12": _safe_float(row.get("rsi_12")),
                "boll_upper": _safe_float(row.get("boll_upper")),
                "boll_mid": _safe_float(row.get("boll_mid")),
                "boll_lower": _safe_float(row.get("boll_lower")),
            })
        return records

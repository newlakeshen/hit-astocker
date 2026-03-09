"""Fetcher for limit_list_d API."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase

FIELDS = (
    "ts_code,trade_date,industry,name,close,pct_chg,amount,limit_amount,"
    "float_mv,total_mv,turnover_ratio,fd_amount,first_time,last_time,"
    "open_times,up_stat,limit_times,limit"
)


class LimitUpFetcher(FetcherBase):
    """Fetch limit-up stocks."""

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "limit_list_d",
            trade_date=date_str,
            limit_type="U",
            fields=FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        return _df_to_records(df)


class LimitDownFetcher(FetcherBase):
    """Fetch limit-down stocks."""

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "limit_list_d",
            trade_date=date_str,
            limit_type="D",
            fields=FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        return _df_to_records(df)


class BrokenBoardFetcher(FetcherBase):
    """Fetch broken-board (炸板) stocks."""

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "limit_list_d",
            trade_date=date_str,
            limit_type="Z",
            fields=FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        return _df_to_records(df)


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        records.append({
            "trade_date": row.get("trade_date", ""),
            "ts_code": row.get("ts_code", ""),
            "name": row.get("name", ""),
            "industry": row.get("industry", ""),
            "close": _safe_float(row.get("close")),
            "pct_chg": _safe_float(row.get("pct_chg")),
            "amount": _safe_float(row.get("amount")),
            "limit_amount": _safe_float(row.get("limit_amount")),
            "float_mv": _safe_float(row.get("float_mv")),
            "total_mv": _safe_float(row.get("total_mv")),
            "turnover_ratio": _safe_float(row.get("turnover_ratio")),
            "fd_amount": _safe_float(row.get("fd_amount")),
            "first_time": row.get("first_time", "") or "",
            "last_time": row.get("last_time", "") or "",
            "open_times": _safe_int(row.get("open_times")),
            "up_stat": row.get("up_stat", "") or "",
            "limit_times": _safe_int(row.get("limit_times")),
            "limit": row.get("limit", ""),
        })
    return records


def _safe_float(v) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _safe_int(v) -> int:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        return int(v)
    except (ValueError, TypeError):
        return 0

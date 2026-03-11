"""Fetcher for top_list and top_inst APIs (dragon-tiger board)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float


class DragonTigerFetcher(FetcherBase):
    """Fetch dragon-tiger board daily data."""

    _FIELDS = (
        "trade_date,ts_code,name,close,pct_change,turnover_rate,"
        "amount,l_sell,l_buy,l_amount,net_amount,net_rate,"
        "amount_rate,float_values,reason"
    )

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "top_list", trade_date=date_str, fields=self._FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", ""),
                "close": _safe_float(row.get("close")),
                "pct_change": _safe_float(row.get("pct_change")),
                "turnover_rate": _safe_float(row.get("turnover_rate")),
                "amount": _safe_float(row.get("amount")),
                "l_sell": _safe_float(row.get("l_sell")),
                "l_buy": _safe_float(row.get("l_buy")),
                "l_amount": _safe_float(row.get("l_amount")),
                "net_amount": _safe_float(row.get("net_amount")),
                "net_rate": _safe_float(row.get("net_rate")),
                "amount_rate": _safe_float(row.get("amount_rate")),
                "float_values": _safe_float(row.get("float_values")),
                "reason": row.get("reason", "") or "",
            })
        return records


class InstitutionalFetcher(FetcherBase):
    """Fetch institutional trading details."""

    _FIELDS = "trade_date,ts_code,exalter,side,buy,buy_rate,sell,sell_rate,net_buy,reason"

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "top_inst", trade_date=date_str, fields=self._FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "exalter": row.get("exalter", "") or "",
                "side": row.get("side", "") or "",
                "buy": _safe_float(row.get("buy")),
                "buy_rate": _safe_float(row.get("buy_rate")),
                "sell": _safe_float(row.get("sell")),
                "sell_rate": _safe_float(row.get("sell_rate")),
                "net_buy": _safe_float(row.get("net_buy")),
                "reason": row.get("reason", "") or "",
            })
        return records

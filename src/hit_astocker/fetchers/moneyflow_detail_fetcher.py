"""Fetcher for moneyflow API (detailed order breakdown)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

FIELDS = (
    "ts_code,trade_date,"
    "buy_sm_vol,buy_sm_amount,sell_sm_vol,sell_sm_amount,"
    "buy_md_vol,buy_md_amount,sell_md_vol,sell_md_amount,"
    "buy_lg_vol,buy_lg_amount,sell_lg_vol,sell_lg_amount,"
    "buy_elg_vol,buy_elg_amount,sell_elg_vol,sell_elg_amount,"
    "net_mf_vol,net_mf_amount"
)


class MoneyFlowDetailFetcher(FetcherBase):
    """Fetch detailed money flow with order size breakdown."""

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query("moneyflow", trade_date=date_str, fields=FIELDS)

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "buy_sm_vol": _safe_float(row.get("buy_sm_vol")),
                "buy_sm_amount": _safe_float(row.get("buy_sm_amount")),
                "sell_sm_vol": _safe_float(row.get("sell_sm_vol")),
                "sell_sm_amount": _safe_float(row.get("sell_sm_amount")),
                "buy_md_vol": _safe_float(row.get("buy_md_vol")),
                "buy_md_amount": _safe_float(row.get("buy_md_amount")),
                "sell_md_vol": _safe_float(row.get("sell_md_vol")),
                "sell_md_amount": _safe_float(row.get("sell_md_amount")),
                "buy_lg_vol": _safe_float(row.get("buy_lg_vol")),
                "buy_lg_amount": _safe_float(row.get("buy_lg_amount")),
                "sell_lg_vol": _safe_float(row.get("sell_lg_vol")),
                "sell_lg_amount": _safe_float(row.get("sell_lg_amount")),
                "buy_elg_vol": _safe_float(row.get("buy_elg_vol")),
                "buy_elg_amount": _safe_float(row.get("buy_elg_amount")),
                "sell_elg_vol": _safe_float(row.get("sell_elg_vol")),
                "sell_elg_amount": _safe_float(row.get("sell_elg_amount")),
                "net_mf_vol": _safe_float(row.get("net_mf_vol")),
                "net_mf_amount": _safe_float(row.get("net_mf_amount")),
            })
        return records

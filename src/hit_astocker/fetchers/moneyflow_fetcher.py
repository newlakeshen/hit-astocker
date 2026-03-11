"""Fetcher for moneyflow_ths API."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float


class MoneyFlowFetcher(FetcherBase):
    _FIELDS = (
        "trade_date,ts_code,name,pct_change,latest,net_amount,"
        "net_d5_amount,buy_lg_amount,buy_lg_amount_rate,"
        "buy_md_amount,buy_md_amount_rate,buy_sm_amount,buy_sm_amount_rate"
    )

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "moneyflow_ths", trade_date=date_str, fields=self._FIELDS,
        )

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "moneyflow_ths", start_date=start_str, end_date=end_str,
            fields=self._FIELDS, page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", ""),
                "pct_change": _safe_float(row.get("pct_change")),
                "latest": _safe_float(row.get("latest")),
                "net_amount": _safe_float(row.get("net_amount")),
                "net_d5_amount": _safe_float(row.get("net_d5_amount")),
                "buy_lg_amount": _safe_float(row.get("buy_lg_amount")),
                "buy_lg_amount_rate": _safe_float(row.get("buy_lg_amount_rate")),
                "buy_md_amount": _safe_float(row.get("buy_md_amount")),
                "buy_md_amount_rate": _safe_float(row.get("buy_md_amount_rate")),
                "buy_sm_amount": _safe_float(row.get("buy_sm_amount")),
                "buy_sm_amount_rate": _safe_float(row.get("buy_sm_amount_rate")),
            })
        return records

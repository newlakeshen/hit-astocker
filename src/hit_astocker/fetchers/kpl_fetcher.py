"""Fetcher for kpl_list API (开盘啦)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float


class KplFetcher(FetcherBase):
    def __init__(self, client, tag: str = "涨停"):
        super().__init__(client)
        self._tag = tag

    _FIELDS = (
        "ts_code,name,trade_date,lu_time,ld_time,lu_desc,tag,theme,"
        "net_change,bid_amount,status,pct_chg,amount,turnover_rate,lu_limit_order"
    )

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "kpl_list", trade_date=date_str, tag=self._tag, fields=self._FIELDS,
        )

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "kpl_list", start_date=start_str, end_date=end_str,
            tag=self._tag, fields=self._FIELDS, page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", ""),
                "lu_time": row.get("lu_time", "") or "",
                "ld_time": row.get("ld_time", "") or "",
                "lu_desc": row.get("lu_desc", "") or "",
                "tag": row.get("tag", "") or "",
                "theme": row.get("theme", "") or "",
                "net_change": _safe_float(row.get("net_change")),
                "bid_amount": _safe_float(row.get("bid_amount")),
                "status": row.get("status", "") or "",
                "pct_chg": _safe_float(row.get("pct_chg")),
                "amount": _safe_float(row.get("amount")),
                "turnover_rate": _safe_float(row.get("turnover_rate")),
                "lu_limit_order": _safe_float(row.get("lu_limit_order")),
            })
        return records

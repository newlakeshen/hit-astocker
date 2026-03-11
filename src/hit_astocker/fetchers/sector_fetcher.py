"""Fetcher for limit_cpt_list API (sector strength)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float, _safe_int


class SectorFetcher(FetcherBase):
    _FIELDS = "ts_code,name,trade_date,days,up_stat,cons_nums,up_nums,pct_chg,rank"

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "limit_cpt_list", trade_date=date_str, fields=self._FIELDS,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "name": row.get("name", ""),
                "days": _safe_int(row.get("days")),
                "up_stat": row.get("up_stat", "") or "",
                "cons_nums": _safe_int(row.get("cons_nums")),
                "up_nums": _safe_int(row.get("up_nums")),
                "pct_chg": _safe_float(row.get("pct_chg")),
                "rank": row.get("rank", "") or "",
            })
        return records

"""Fetcher for anns_d API (上市公司公告)."""

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase

FIELDS = "ts_code,ann_date,title,ann_type,content"


class AnnouncementFetcher(FetcherBase):
    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query("anns_d", ann_date=date_str, fields=FIELDS)

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "anns_d", start_date=start_str, end_date=end_str,
            fields=FIELDS, page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "ann_date": row.get("ann_date", ""),
                "ts_code": row.get("ts_code", ""),
                "title": row.get("title", "") or "",
                "ann_type": row.get("ann_type", "") or "",
                "content": row.get("content", "") or "",
            })
        return records

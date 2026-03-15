"""Fetcher for ths_member API (同花顺概念成分股).

Per-concept on-demand API: query by ts_code (concept index code) to get
member stocks.
"""

import logging

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float

logger = logging.getLogger(__name__)

FIELDS = "ts_code,code,name,weight,in_date,out_date,is_new"


class ThsMemberFetcher(FetcherBase):
    """Fetch THS concept member stocks for a list of concept codes."""

    def fetch_for_concepts(self, concept_codes: list[str]) -> list[dict]:
        """Fetch ths_member for each concept code (on-demand)."""
        all_records: list[dict] = []
        for code in concept_codes:
            try:
                df = self._client.query(
                    "ths_member",
                    ts_code=code,
                    fields=FIELDS,
                )
                if not df.empty:
                    all_records.extend(self._transform(df))
            except Exception:
                logger.debug("ths_member failed for concept %s", code)
                continue
        return all_records

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return pd.DataFrame()  # Not used in daily bulk sync

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "ts_code": row.get("ts_code", "") or "",
                "code": row.get("code", "") or "",
                "name": row.get("name", "") or "",
                "weight": _safe_float(row.get("weight")),
                "in_date": row.get("in_date", "") or "",
                "out_date": row.get("out_date") or None,
                "is_new": row.get("is_new", "") or "",
            })
        return records

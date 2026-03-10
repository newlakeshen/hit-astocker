"""Fetcher for concept_detail API (概念板块成分).

Per-stock on-demand API: query by ts_code to find which concepts a stock
belongs to.  Follows the same batch pattern as stk_factor_fetcher.
"""

import logging

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase

logger = logging.getLogger(__name__)

FIELDS = "id,concept_name,ts_code,name,in_date,out_date"


class ConceptDetailFetcher(FetcherBase):
    """Fetch concept memberships for a list of stock codes."""

    def fetch_for_codes(self, ts_codes: list[str]) -> list[dict]:
        """Fetch concept_detail for each stock code (on-demand)."""
        all_records: list[dict] = []
        for code in ts_codes:
            try:
                df = self._client.query(
                    "concept_detail",
                    ts_code=code,
                    fields=FIELDS,
                )
                if not df.empty:
                    all_records.extend(self._transform(df))
            except Exception:
                logger.debug("concept_detail failed for %s", code)
                continue
        return all_records

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return pd.DataFrame()  # Not used in daily bulk sync

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "id": row.get("id", "") or "",
                "concept_name": row.get("concept_name", "") or "",
                "ts_code": row.get("ts_code", "") or "",
                "name": row.get("name", "") or "",
                "in_date": row.get("in_date", "") or "",
                "out_date": row.get("out_date", "") or "",
            })
        return records

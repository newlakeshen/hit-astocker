"""Fetchers for hm_list (游资名录) and hm_detail (游资每日明细)."""

import logging

import pandas as pd

from hit_astocker.fetchers.fetcher_base import FetcherBase
from hit_astocker.fetchers.limit_fetcher import _safe_float
from hit_astocker.fetchers.tushare_client import TushareClient

logger = logging.getLogger(__name__)

HM_DETAIL_FIELDS = (
    "trade_date,ts_code,ts_name,buy_amount,sell_amount,net_amount,"
    "hm_name,hm_orgs,tag"
)


class HmDetailFetcher(FetcherBase):
    """Fetch daily hot money trading details (hm_detail)."""

    def _call_api(self, date_str: str) -> pd.DataFrame:
        return self._client.query(
            "hm_detail",
            trade_date=date_str,
            fields=HM_DETAIL_FIELDS,
        )

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        return self._client.query(
            "hm_detail",
            start_date=start_str, end_date=end_str,
            fields=HM_DETAIL_FIELDS, page_size=5000,
        )

    def _transform(self, df: pd.DataFrame) -> list[dict]:
        records = []
        for _, row in df.iterrows():
            records.append({
                "trade_date": row.get("trade_date", ""),
                "ts_code": row.get("ts_code", ""),
                "ts_name": row.get("ts_name", "") or "",
                "buy_amount": _safe_float(row.get("buy_amount")),
                "sell_amount": _safe_float(row.get("sell_amount")),
                "net_amount": _safe_float(row.get("net_amount")),
                "hm_name": row.get("hm_name", "") or "",
                "hm_orgs": row.get("hm_orgs", "") or "",
                "tag": row.get("tag", "") or "",
            })
        return records


def sync_hm_list(client: TushareClient, conn) -> int:
    """One-time sync of hm_list (游资名录) into hm_list table.

    hm_list is a static roster (~500 records) that rarely changes.
    """
    from hit_astocker.repositories.base import BaseRepository

    df = client.query("hm_list", fields="name,desc,orgs")
    if df.empty:
        logger.warning("hm_list returned empty")
        return 0

    records = []
    for _, row in df.iterrows():
        records.append({
            "hm_name": row.get("name", "") or "",
            "desc": row.get("desc", "") or "",
            "orgs": row.get("orgs", "") or "",
        })

    repo = BaseRepository(conn, "hm_list")
    count = repo.upsert_many(records)
    logger.info("hm_list: synced %d trader records", count)
    return count

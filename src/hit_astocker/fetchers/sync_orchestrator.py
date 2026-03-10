"""Orchestrates data sync from all Tushare APIs."""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

from rich.progress import Progress, SpinnerColumn, TextColumn

from hit_astocker.config.settings import Settings
from hit_astocker.fetchers.daily_bar_fetcher import DailyBarFetcher
from hit_astocker.fetchers.dragon_fetcher import DragonTigerFetcher, InstitutionalFetcher
from hit_astocker.fetchers.hsgt_fetcher import HsgtTop10Fetcher
from hit_astocker.fetchers.index_fetcher import IndexDailyFetcher
from hit_astocker.fetchers.kpl_fetcher import KplFetcher
from hit_astocker.fetchers.limit_fetcher import BrokenBoardFetcher, LimitDownFetcher, LimitUpFetcher
from hit_astocker.fetchers.moneyflow_detail_fetcher import MoneyFlowDetailFetcher
from hit_astocker.fetchers.moneyflow_fetcher import MoneyFlowFetcher
from hit_astocker.fetchers.sector_fetcher import SectorFetcher
from hit_astocker.fetchers.step_fetcher import StepFetcher
from hit_astocker.fetchers.ths_hot_fetcher import ThsHotFetcher
from hit_astocker.fetchers.tushare_client import TushareClient
from hit_astocker.repositories.base import BaseRepository
from hit_astocker.utils.date_utils import to_tushare_date

logger = logging.getLogger(__name__)

# API name -> (table_name, fetcher_class, extra_kwargs)
API_REGISTRY: list[tuple[str, str, type, dict[str, Any]]] = [
    ("limit_list_d_U", "limit_list_d", LimitUpFetcher, {}),
    ("limit_list_d_D", "limit_list_d", LimitDownFetcher, {}),
    ("limit_list_d_Z", "limit_list_d", BrokenBoardFetcher, {}),
    ("limit_step", "limit_step", StepFetcher, {}),
    ("limit_cpt_list", "limit_cpt_list", SectorFetcher, {}),
    ("kpl_list", "kpl_list", KplFetcher, {"tag": "涨停"}),
    ("top_list", "top_list", DragonTigerFetcher, {}),
    ("top_inst", "top_inst", InstitutionalFetcher, {}),
    ("moneyflow_ths", "moneyflow_ths", MoneyFlowFetcher, {}),
    ("moneyflow_detail", "moneyflow_detail", MoneyFlowDetailFetcher, {}),
    ("daily_bar", "daily_bar", DailyBarFetcher, {}),
    ("index_daily", "index_daily", IndexDailyFetcher, {}),
    ("ths_hot", "ths_hot", ThsHotFetcher, {}),
    ("hsgt_top10", "hsgt_top10", HsgtTop10Fetcher, {}),
]


class SyncOrchestrator:
    def __init__(self, settings: Settings, conn: sqlite3.Connection):
        self._client = TushareClient(
            settings.tushare_token,
            batch_size=settings.api_batch_size,
            timeout=settings.api_timeout,
        )
        self._conn = conn

    def sync_date(self, trade_date: date, apis: list[str] | None = None) -> dict[str, int]:
        """Sync all APIs for a given date. Returns {api_name: record_count}.

        Fetches data from all APIs in parallel (I/O-bound HTTP calls),
        then writes to DB sequentially (SQLite single-writer constraint).
        """
        results = {}
        date_str = to_tushare_date(trade_date)

        # Filter APIs
        registry = [
            (api_name, table_name, fetcher_cls, kwargs)
            for api_name, table_name, fetcher_cls, kwargs in API_REGISTRY
            if not apis or api_name in apis
        ]

        # Phase 1: Fetch all API data in parallel (HTTP I/O)
        fetched: dict[str, tuple[str, list]] = {}  # api_name -> (table_name, records)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("Fetching data from APIs...", total=None)

            def _fetch_one(item):
                api_name, _table, fetcher_cls, kwargs = item
                fetcher = fetcher_cls(self._client, **kwargs)
                return api_name, fetcher.fetch(trade_date)

            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(_fetch_one, item): item for item in registry}
                for future in as_completed(futures):
                    item = futures[future]
                    api_name = item[0]
                    table_name = item[1]
                    try:
                        _, records = future.result()
                        fetched[api_name] = (table_name, records or [])
                    except Exception as e:
                        logger.error("Fetch failed for %s: %s", api_name, e)
                        fetched[api_name] = (table_name, None)

            progress.update(task, description=f"[green]Fetched {len(fetched)} APIs")

            # Phase 2: Write to DB sequentially
            for api_name, table_name, _, _ in registry:
                table, records = fetched.get(api_name, (table_name, None))
                if records is None:
                    results[api_name] = -1
                    self._log_sync(api_name, date_str, 0, "error", "fetch failed")
                elif records:
                    repo = BaseRepository(self._conn, table)
                    count = repo.upsert_many(records)
                    results[api_name] = count
                    self._log_sync(api_name, date_str, count, "success")
                else:
                    results[api_name] = 0
                    self._log_sync(api_name, date_str, 0, "empty")

        self._conn.commit()
        return results

    def sync_date_range(self, start: date, end: date) -> dict[str, dict[str, int]]:
        """Sync all APIs for a date range."""
        from hit_astocker.utils.date_utils import date_range

        all_results = {}
        for d in date_range(start, end):
            if d.weekday() >= 5:  # Skip weekends
                continue
            logger.info("Syncing date: %s", d)
            all_results[to_tushare_date(d)] = self.sync_date(d)
        return all_results

    def _log_sync(
        self, api_name: str, date_str: str, count: int, status: str, error: str = ""
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO sync_log (api_name, trade_date, record_count, status, error_msg)
               VALUES (?, ?, ?, ?, ?)""",
            (api_name, date_str, count, status, error),
        )

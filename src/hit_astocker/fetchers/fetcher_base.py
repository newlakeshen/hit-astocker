"""Base fetcher with retry logic."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import pandas as pd

from hit_astocker.fetchers.tushare_client import TushareClient
from hit_astocker.utils.date_utils import to_tushare_date

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds


class FetcherBase(ABC):
    def __init__(self, client: TushareClient):
        self._client = client

    # -- Single-day fetch (existing) ------------------------------------------

    def fetch(self, trade_date: date) -> list[Any]:
        """Fetch data for a date with retry logic."""
        date_str = to_tushare_date(trade_date)
        for attempt in range(MAX_RETRIES):
            try:
                df = self._call_api(date_str)
                if df.empty:
                    return []
                return self._transform(df)
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "Retry %d/%d for %s on %s: %s (waiting %ds)",
                        attempt + 1, MAX_RETRIES, self.__class__.__name__, date_str, e, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Failed after %d retries for %s on %s: %s",
                        MAX_RETRIES, self.__class__.__name__, date_str, e,
                    )
                    raise

    # -- Date-range fetch (batch) ---------------------------------------------

    @classmethod
    def supports_range(cls) -> bool:
        """Whether this fetcher supports date range queries."""
        return cls._call_api_range is not FetcherBase._call_api_range

    def fetch_range(self, start_date: date, end_date: date) -> list[Any]:
        """Fetch data for a date range with retry logic.

        Returns all records in [start_date, end_date].
        Only works if the subclass overrides ``_call_api_range``.
        """
        start_str = to_tushare_date(start_date)
        end_str = to_tushare_date(end_date)
        for attempt in range(MAX_RETRIES):
            try:
                df = self._call_api_range(start_str, end_str)
                if df.empty:
                    return []
                return self._transform(df)
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "Retry %d/%d for %s range %s~%s: %s (waiting %ds)",
                        attempt + 1, MAX_RETRIES, self.__class__.__name__,
                        start_str, end_str, e, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Failed after %d retries for %s range %s~%s: %s",
                        MAX_RETRIES, self.__class__.__name__, start_str, end_str, e,
                    )
                    raise

    # -- Abstract methods -----------------------------------------------------

    @abstractmethod
    def _call_api(self, date_str: str) -> pd.DataFrame:
        """Call the specific Tushare API for a single date."""

    def _call_api_range(self, start_str: str, end_str: str) -> pd.DataFrame:
        """Call the specific Tushare API for a date range.

        Override in subclass to enable batch fetching.
        Default: raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support range queries"
        )

    @abstractmethod
    def _transform(self, df: pd.DataFrame) -> list[Any]:
        """Transform DataFrame to domain model list."""

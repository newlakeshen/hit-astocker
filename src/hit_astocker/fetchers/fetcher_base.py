"""Base fetcher with retry logic."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import date
from typing import Any

import pandas as pd

from hit_astocker.fetchers.rate_limiter import RateLimiter
from hit_astocker.fetchers.tushare_client import TushareClient
from hit_astocker.utils.date_utils import to_tushare_date

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # seconds


class FetcherBase(ABC):
    def __init__(self, client: TushareClient, rate_limiter: RateLimiter):
        self._client = client
        self._limiter = rate_limiter

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

    @abstractmethod
    def _call_api(self, date_str: str) -> pd.DataFrame:
        """Call the specific Tushare API."""

    @abstractmethod
    def _transform(self, df: pd.DataFrame) -> list[Any]:
        """Transform DataFrame to domain model list."""

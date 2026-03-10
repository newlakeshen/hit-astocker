"""Tushare Pro API client wrapper."""

import logging

import pandas as pd
import tushare as ts

logger = logging.getLogger(__name__)


class TushareClient:
    def __init__(self, token: str, batch_size: int = 50, rate_limiter=None, timeout: int = 60):
        if not token:
            raise ValueError("Tushare token is required. Set TUSHARE_TOKEN env var.")
        self._pro = ts.pro_api(token, timeout=timeout)
        self._batch_size = batch_size
        self._limiter = rate_limiter

    @property
    def pro(self):
        return self._pro

    def query(self, api_name: str, fields: str = "", **kwargs) -> pd.DataFrame:
        """Call a Tushare Pro API with automatic pagination (limit/offset).

        Each page fetches at most `self._batch_size` records, then merges.
        """
        all_dfs: list[pd.DataFrame] = []
        offset = 0

        while True:
            if self._limiter:
                self._limiter.acquire()

            logger.info(
                "Calling Tushare API: %s offset=%d limit=%d params=%s",
                api_name, offset, self._batch_size, kwargs,
            )
            try:
                call_kwargs = {**kwargs, "limit": self._batch_size, "offset": offset}
                if fields:
                    df = self._pro.query(api_name, fields=fields, **call_kwargs)
                else:
                    df = self._pro.query(api_name, **call_kwargs)
            except Exception as e:
                logger.error("Tushare API error for %s: %s", api_name, e)
                raise

            if df is None or df.empty:
                break

            all_dfs.append(df)
            fetched = len(df)
            logger.info("Got %d records from %s (offset=%d)", fetched, api_name, offset)

            if fetched < self._batch_size:
                break
            offset += fetched

        if not all_dfs:
            logger.warning("Empty response from %s", api_name)
            return pd.DataFrame()

        result = pd.concat(all_dfs, ignore_index=True)
        logger.info("Total %d records from %s (%d pages)", len(result), api_name, len(all_dfs))
        return result

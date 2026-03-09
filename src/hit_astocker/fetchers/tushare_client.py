"""Tushare Pro API client wrapper."""

import logging

import pandas as pd
import tushare as ts

logger = logging.getLogger(__name__)


class TushareClient:
    def __init__(self, token: str):
        if not token:
            raise ValueError("Tushare token is required. Set TUSHARE_TOKEN env var.")
        self._pro = ts.pro_api(token)

    @property
    def pro(self):
        return self._pro

    def query(self, api_name: str, fields: str = "", **kwargs) -> pd.DataFrame:
        """Call a Tushare Pro API and return DataFrame."""
        logger.info("Calling Tushare API: %s with params: %s", api_name, kwargs)
        try:
            if fields:
                df = self._pro.query(api_name, fields=fields, **kwargs)
            else:
                df = self._pro.query(api_name, **kwargs)
            if df is None or df.empty:
                logger.warning("Empty response from %s", api_name)
                return pd.DataFrame()
            logger.info("Got %d records from %s", len(df), api_name)
            return df
        except Exception as e:
            logger.error("Tushare API error for %s: %s", api_name, e)
            raise

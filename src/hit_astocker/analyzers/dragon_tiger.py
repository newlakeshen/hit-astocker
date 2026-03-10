"""Dragon-tiger board (龙虎榜) analysis engine.

Combines top_list / top_inst (traditional) with hm_detail (quantified
hot money profiles) for a data-driven seat analysis.

When hm_detail data is available:
  - Trader win rate, T+1 premium, coordination — all from actual trade records
  - No more hardcoded broker keywords

When hm_detail is NOT yet synced (graceful fallback):
  - Uses top_inst institutional net buy only
  - seat_scores dict will be empty
"""

import sqlite3
from datetime import date

from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.repositories.dragon_tiger_repo import (
    DragonTigerRepository,
    InstitutionalTradeRepository,
)
from hit_astocker.repositories.hm_repo import HmRepository


class DragonTigerAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._dt_repo = DragonTigerRepository(conn)
        self._inst_repo = InstitutionalTradeRepository(conn)
        self._hm_repo = HmRepository(conn)

    def analyze(self, trade_date: date) -> DragonTigerResult:
        records = self._dt_repo.find_records_by_date(trade_date)
        inst_net_buy = self._inst_repo.get_institutional_net_buy(trade_date)

        # Quantified seat analysis from hm_detail (if data exists)
        seat_scores = {}
        if self._hm_repo.has_data():
            profiles = self._hm_repo.compute_trader_profiles(trade_date)
            seat_scores = self._hm_repo.compute_seat_scores(trade_date, profiles)

        return DragonTigerResult(
            trade_date=trade_date,
            records=tuple(records),
            institutional_net_buy=dict(inst_net_buy),
            seat_scores=seat_scores,
        )

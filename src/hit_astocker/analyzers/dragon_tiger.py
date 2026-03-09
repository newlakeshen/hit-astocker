"""Dragon-tiger board (龙虎榜) analysis engine.

Analyzes institutional and hot-money seat activity on limit-up stocks.
"""

import sqlite3
from collections import defaultdict
from datetime import date

from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.repositories.dragon_tiger_repo import (
    DragonTigerRepository,
    InstitutionalTradeRepository,
)

# Known hot-money seats (游资席位) - extensible via config
KNOWN_HOT_MONEY_KEYWORDS = [
    "华鑫证券上海分公司",
    "东方财富拉萨",
    "国泰君安上海江苏路",
    "中信证券上海分公司",
    "华泰证券深圳益田路",
    "中国银河绍兴",
    "东方证券上海浦东新区",
    "国盛证券宁波桑田路",
    "申万宏源上海闵行区",
    "方正证券杭州",
]


class DragonTigerAnalyzer:
    def __init__(self, conn: sqlite3.Connection, hot_money_keywords: list[str] | None = None):
        self._dt_repo = DragonTigerRepository(conn)
        self._inst_repo = InstitutionalTradeRepository(conn)
        self._hot_money = hot_money_keywords or KNOWN_HOT_MONEY_KEYWORDS

    def analyze(self, trade_date: date) -> DragonTigerResult:
        records = self._dt_repo.find_records_by_date(trade_date)
        inst_trades = self._inst_repo.find_records_by_date(trade_date)

        # Institutional net buy per stock
        inst_net_buy = self._inst_repo.get_institutional_net_buy(trade_date)

        # Hot money seat detection per stock
        hot_money_seats: dict[str, list[str]] = defaultdict(list)
        for trade in inst_trades:
            if self._is_hot_money(trade.exalter) and trade.side == "0":  # Buy side
                hot_money_seats[trade.ts_code].append(trade.exalter)

        # Cooperation detection: 2+ known hot-money seats on same stock
        cooperation = tuple(
            code for code, seats in hot_money_seats.items() if len(seats) >= 2
        )

        return DragonTigerResult(
            trade_date=trade_date,
            records=tuple(records),
            institutional_net_buy=dict(inst_net_buy),
            hot_money_seats=dict(hot_money_seats),
            cooperation_flags=cooperation,
        )

    def _is_hot_money(self, exalter: str) -> bool:
        return any(kw in exalter for kw in self._hot_money)

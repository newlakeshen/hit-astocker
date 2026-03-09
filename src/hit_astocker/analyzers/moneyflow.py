"""Money flow analysis engine."""

import sqlite3
from datetime import date

from hit_astocker.models.analysis_result import MoneyFlowResult
from hit_astocker.repositories.moneyflow_repo import MoneyFlowRepository


class MoneyFlowAnalyzer:
    def __init__(self, conn: sqlite3.Connection):
        self._repo = MoneyFlowRepository(conn)

    def analyze(self, trade_date: date, ts_codes: list[str] | None = None) -> list[MoneyFlowResult]:
        """Analyze money flow for given stocks or top inflow stocks."""
        if ts_codes:
            records = [
                self._repo.find_by_stock(trade_date, code)
                for code in ts_codes
            ]
            records = [r for r in records if r is not None]
        else:
            records = self._repo.find_top_inflow(trade_date, top_n=30)

        results = []
        for rec in records:
            strength = self._classify_flow(rec.net_amount, rec.buy_lg_amount)
            results.append(MoneyFlowResult(
                trade_date=rec.trade_date,
                ts_code=rec.ts_code,
                name=rec.name,
                net_amount=rec.net_amount,
                buy_lg_amount=rec.buy_lg_amount,
                buy_lg_amount_rate=rec.buy_lg_amount_rate,
                flow_strength=strength,
            ))

        return sorted(results, key=lambda r: r.net_amount, reverse=True)

    @staticmethod
    def _classify_flow(net_amount: float, buy_lg_amount: float) -> str:
        """Classify capital flow strength."""
        if net_amount > 5000 and buy_lg_amount > 3000:
            return "STRONG_IN"
        if net_amount > 0:
            return "WEAK_IN"
        if net_amount > -2000:
            return "NEUTRAL"
        if net_amount > -5000:
            return "WEAK_OUT"
        return "STRONG_OUT"

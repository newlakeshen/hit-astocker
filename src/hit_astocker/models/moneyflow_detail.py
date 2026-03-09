"""Detailed money flow model with order size breakdown."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MoneyFlowDetail:
    trade_date: date
    ts_code: str
    # 小单 (<=5万)
    buy_sm_vol: float
    buy_sm_amount: float
    sell_sm_vol: float
    sell_sm_amount: float
    # 中单 (5-20万)
    buy_md_vol: float
    buy_md_amount: float
    sell_md_vol: float
    sell_md_amount: float
    # 大单 (20-100万)
    buy_lg_vol: float
    buy_lg_amount: float
    sell_lg_vol: float
    sell_lg_amount: float
    # 特大单 (>=100万)
    buy_elg_vol: float
    buy_elg_amount: float
    sell_elg_vol: float
    sell_elg_amount: float
    # 汇总
    net_mf_vol: float
    net_mf_amount: float

    @property
    def net_sm(self) -> float:
        return self.buy_sm_amount - self.sell_sm_amount

    @property
    def net_md(self) -> float:
        return self.buy_md_amount - self.sell_md_amount

    @property
    def net_lg(self) -> float:
        return self.buy_lg_amount - self.sell_lg_amount

    @property
    def net_elg(self) -> float:
        return self.buy_elg_amount - self.sell_elg_amount

    @property
    def main_force_net(self) -> float:
        """主力净流入 = 大单 + 特大单 净流入"""
        return self.net_lg + self.net_elg

    @property
    def total_buy(self) -> float:
        return self.buy_sm_amount + self.buy_md_amount + self.buy_lg_amount + self.buy_elg_amount

    @property
    def total_sell(self) -> float:
        return self.sell_sm_amount + self.sell_md_amount + self.sell_lg_amount + self.sell_elg_amount

    @property
    def elg_ratio(self) -> float:
        """特大单占总成交比例"""
        total = self.total_buy + self.total_sell
        if total <= 0:
            return 0.0
        return (self.buy_elg_amount + self.sell_elg_amount) / total

    @property
    def main_force_ratio(self) -> float:
        """主力(大单+特大单)占总成交比例"""
        total = self.total_buy + self.total_sell
        if total <= 0:
            return 0.0
        return (
            self.buy_lg_amount + self.sell_lg_amount + self.buy_elg_amount + self.sell_elg_amount
        ) / total

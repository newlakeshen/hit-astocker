"""北向资金(沪港通/深港通)数据模型."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class HsgtTop10Record:
    """北向资金每日十大成交股."""

    trade_date: date
    ts_code: str
    name: str
    close: float
    change: float  # 涨跌额
    rank: int  # 排名
    market_type: str  # 1=沪股通, 3=深股通
    amount: float  # 成交金额 (万元)
    net_amount: float  # 净买入额 (万元)
    buy: float  # 买入额 (万元)
    sell: float  # 卖出额 (万元)

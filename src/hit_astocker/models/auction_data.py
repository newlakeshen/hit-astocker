"""集合竞价数据模型."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AuctionRecord:
    """个股集合竞价记录."""

    trade_date: date
    ts_code: str
    name: str
    open: float  # 开盘价
    pre_close: float  # 昨收价
    change: float  # 涨跌额
    pct_change: float  # 竞价涨跌幅 (%)
    vol: float  # 竞价成交量
    amount: float  # 竞价成交额 (万元)

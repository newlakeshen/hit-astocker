"""同花顺热股排名数据模型."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ThsHotRecord:
    """同花顺热股排名记录."""

    trade_date: date
    ts_code: str
    ts_name: str
    rank: int  # 热度排名
    pct_change: float  # 涨跌幅
    concept: str  # 所属概念
    hot: int  # 热度值 (越高越热)
    market: str  # 市场类型 (热股/概念/ETF)

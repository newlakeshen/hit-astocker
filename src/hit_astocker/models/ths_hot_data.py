"""同花顺热股排名数据模型."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ThsHotRecord:
    """同花顺热股排名记录."""

    trade_date: date
    ts_code: str
    ts_name: str
    data_type: str  # 类型 (热股/概念/ETF)
    current_price: float  # 当前价格
    rank: int  # 热度排名
    pct_change: float  # 涨跌幅
    rank_reason: str  # 上榜原因 (e.g. "涨停", "机构大买")
    rank_time: str  # 上榜时间 (HH:MM:SS)
    concept: str  # 所属概念
    hot: int  # 热度值 (越高越热)
    market: str  # 市场类型 (热股/概念/ETF)

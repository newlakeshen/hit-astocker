from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class KplRecord:
    ts_code: str
    name: str
    trade_date: date
    lu_time: str  # 涨停时间
    ld_time: str  # 跌停时间
    lu_desc: str  # 涨停原因
    tag: str  # 类型: 涨停/炸板/跌停/自然涨停/竞价
    theme: str  # 题材
    net_change: float  # 净变化
    bid_amount: float  # 竞价金额
    status: str  # 连板状态
    pct_chg: float
    amount: float
    turnover_rate: float
    lu_limit_order: float  # 涨停封单

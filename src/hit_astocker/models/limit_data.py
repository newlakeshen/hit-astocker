from dataclasses import dataclass
from datetime import date
from enum import Enum


class LimitDirection(str, Enum):
    UP = "U"  # 涨停
    DOWN = "D"  # 跌停
    BROKEN = "Z"  # 炸板


@dataclass(frozen=True)
class LimitRecord:
    trade_date: date
    ts_code: str
    name: str
    industry: str
    close: float
    pct_chg: float
    amount: float  # 成交额 (万元)
    limit_amount: float  # 封单金额
    float_mv: float  # 流通市值
    total_mv: float  # 总市值
    turnover_ratio: float  # 换手率
    fd_amount: float  # 封单手数
    first_time: str  # 首次封板时间 HH:MM:SS
    last_time: str  # 最后封板时间
    open_times: int  # 打开次数
    up_stat: str  # 涨停统计
    limit_times: int  # 连板次数
    limit: LimitDirection  # 涨停/跌停/炸板

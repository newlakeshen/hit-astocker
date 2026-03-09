from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ConsecutiveLimitRecord:
    ts_code: str
    name: str
    trade_date: date
    nums: int  # 连板天数

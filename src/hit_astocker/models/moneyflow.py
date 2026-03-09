from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class MoneyFlowRecord:
    trade_date: date
    ts_code: str
    name: str
    pct_change: float
    latest: float  # 最新价
    net_amount: float  # 净流入额 (万元)
    net_d5_amount: float  # 5日主力净额 (万元)
    buy_lg_amount: float  # 大单净流入 (万元)
    buy_lg_amount_rate: float  # 大单净流入占比
    buy_md_amount: float  # 中单净流入 (万元)
    buy_md_amount_rate: float  # 中单净流入占比
    buy_sm_amount: float  # 小单净流入 (万元)
    buy_sm_amount_rate: float  # 小单净流入占比

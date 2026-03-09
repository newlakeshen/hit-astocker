from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DragonTigerRecord:
    trade_date: date
    ts_code: str
    name: str
    close: float
    pct_change: float
    turnover_rate: float
    amount: float  # 总成交额
    l_sell: float  # 龙虎榜卖出额
    l_buy: float  # 龙虎榜买入额
    l_amount: float  # 龙虎榜成交额
    net_amount: float  # 龙虎榜净买入额
    net_rate: float  # 龙虎榜净买率
    amount_rate: float  # 龙虎榜成交占比
    float_values: float  # 流通市值
    reason: str  # 上榜原因


@dataclass(frozen=True)
class InstitutionalTrade:
    trade_date: date
    ts_code: str
    exalter: str  # 机构/营业部名称
    side: str  # 0=买入前五, 1=卖出前五
    buy: float  # 买入额
    buy_rate: float  # 买入占比
    sell: float  # 卖出额
    sell_rate: float  # 卖出占比
    net_buy: float  # 净买入额
    reason: str


@dataclass(frozen=True)
class DragonTigerResult:
    trade_date: date
    records: tuple[DragonTigerRecord, ...]
    institutional_net_buy: dict[str, float]  # ts_code -> net buy
    hot_money_seats: dict[str, list[str]]  # ts_code -> seat names
    cooperation_flags: tuple[str, ...]  # ts_codes with multi-seat cooperation

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class FirstBoardResult:
    trade_date: date
    ts_code: str
    name: str
    industry: str
    close: float
    pct_chg: float
    seal_time_score: float  # 封板时间评分
    seal_strength_score: float  # 封板强度评分
    purity_score: float  # 封板纯度评分
    turnover_score: float  # 换手评分
    sector_score: float  # 板块评分
    composite_score: float  # 综合评分
    first_time: str
    open_times: int
    limit_amount: float
    float_mv: float
    turnover_ratio: float
    sector_name: str = ""


@dataclass(frozen=True)
class LianbanTier:
    height: int  # 连板高度 (2板, 3板, ...)
    stocks: tuple[str, ...]  # (ts_code, ...)
    stock_names: tuple[str, ...]
    count: int
    yesterday_count: int  # 昨日该高度的数量
    promotion_rate: float  # 晋级率


@dataclass(frozen=True)
class LianbanResult:
    trade_date: date
    tiers: tuple[LianbanTier, ...]  # 各层级连板数据
    max_height: int  # 最高连板高度
    leader_code: str  # 空间板龙头代码
    leader_name: str  # 空间板龙头名称
    total_lianban_count: int  # 连板总数
    avg_promotion_rate: float  # 平均晋级率
    height_trend: tuple[int, ...] = ()  # 近N日最高连板高度趋势


@dataclass(frozen=True)
class MoneyFlowResult:
    trade_date: date
    ts_code: str
    name: str
    net_amount: float
    buy_lg_amount: float
    buy_lg_amount_rate: float
    flow_strength: str  # STRONG_IN / WEAK_IN / NEUTRAL / WEAK_OUT / STRONG_OUT

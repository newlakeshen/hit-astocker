from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hit_astocker.models.index_data import MarketContext


@dataclass(frozen=True)
class SentimentScore:
    trade_date: date
    limit_up_count: int  # 涨停家数
    limit_down_count: int  # 跌停家数
    broken_count: int  # 炸板家数
    up_down_ratio: float  # 涨停/跌停比
    broken_rate: float  # 炸板率
    max_consecutive_height: int  # 最高连板高度
    avg_consecutive_height: float  # 平均连板高度
    promotion_rate: float  # 总晋级率
    money_effect_score: float  # 赚钱效应评分 (0-100)
    overall_score: float  # 综合情绪评分 (0-100)
    risk_level: str  # LOW / MEDIUM / HIGH / EXTREME
    description: str  # 市场概述
    # ── 9-factor 新增指标 (defaults for backward compat) ──
    prev_limit_up_premium: float = 0.0  # 昨日涨停次日溢价率 (%)
    recovery_count: int = 0  # 回封数 (limit='U' AND open_times>0)
    broken_recovery_rate: float = 0.0  # 炸板修复率
    yizi_count: int = 0  # 一字板家数
    yizi_ratio: float = 0.0  # 一字板占比 (yizi / limit_up)
    limit_up_10cm: int = 0  # 10cm涨停数 (主板 00/60)
    limit_up_20cm: int = 0  # 20cm涨停数 (创/科 30/68)
    broken_10cm: int = 0  # 10cm炸板数
    broken_20cm: int = 0  # 20cm炸板数
    promo_rate_2to3: float = 0.0  # 2板→3板晋级率
    promo_rate_3to4: float = 0.0  # 3板→4板晋级率
    auction_avg_pct: float = 0.0  # 竞价平均涨幅 (%)
    auction_up_ratio: float = 0.0  # 竞价高开比例
    market_context: MarketContext | None = field(default=None)  # 大盘环境

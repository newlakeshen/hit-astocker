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
    promotion_rate: float  # 晋级率
    money_effect_score: float  # 赚钱效应评分 (0-100)
    overall_score: float  # 综合情绪评分 (0-100)
    risk_level: str  # LOW / MEDIUM / HIGH / EXTREME
    description: str  # 市场概述
    market_context: MarketContext | None = field(default=None)  # 大盘环境

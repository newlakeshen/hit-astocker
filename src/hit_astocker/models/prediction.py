"""Prediction result models."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class FactorScore:
    """Single factor score with metadata."""
    name: str
    value: float  # Raw value
    score: float  # Normalized 0-100
    weight: float  # Weight in composite
    description: str = ""


@dataclass(frozen=True)
class StockPrediction:
    trade_date: date
    ts_code: str
    name: str
    direction: Direction
    confidence: float  # 0-100
    predicted_pct: float  # 预测涨跌幅
    factor_scores: tuple[FactorScore, ...] = ()
    reason: str = ""
    sector: str = ""
    close: float = 0.0
    pct_chg: float = 0.0


@dataclass(frozen=True)
class PredictionReport:
    trade_date: date
    buy_candidates: tuple[StockPrediction, ...]
    sell_candidates: tuple[StockPrediction, ...]
    market_score: float  # 市场综合评分
    market_description: str = ""

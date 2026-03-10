"""DailyAnalysisContext — 当日全量分析结果的不可变容器.

一次构建，多处复用（dashboard / signal / backtest），避免重复计算。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from hit_astocker.analyzers.board_survival import SurvivalModel
from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult, MoneyFlowResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult, StockSentimentScore
from hit_astocker.models.sector import SectorRotationResult
from hit_astocker.models.sentiment import SentimentScore


@dataclass(frozen=True)
class DailyAnalysisContext:
    """Holds every analyzer result for a single trading day."""

    trade_date: date
    sentiment: SentimentScore
    firstboard: tuple[FirstBoardResult, ...]
    lianban: LianbanResult
    sector: SectorRotationResult
    dragon: DragonTigerResult
    event: EventAnalysisResult
    survival_model: SurvivalModel | None
    hsgt_net_map: dict[str, float]
    moneyflow: tuple[MoneyFlowResult, ...]
    stock_sentiments: tuple[StockSentimentScore, ...]


def build_daily_context(
    conn: sqlite3.Connection,
    settings,
    trade_date: date,
) -> DailyAnalysisContext:
    """Run all analyzers once and return an immutable context.

    Parameters
    ----------
    conn : sqlite3.Connection
    settings : hit_astocker.config.settings.Settings
    trade_date : date
    """
    from hit_astocker.analyzers.board_survival import BoardSurvivalAnalyzer
    from hit_astocker.analyzers.dragon_tiger import DragonTigerAnalyzer
    from hit_astocker.analyzers.event_classifier import EventClassifier
    from hit_astocker.analyzers.firstboard import FirstBoardAnalyzer
    from hit_astocker.analyzers.lianban import LianbanAnalyzer
    from hit_astocker.analyzers.moneyflow import MoneyFlowAnalyzer
    from hit_astocker.analyzers.sector_rotation import SectorRotationAnalyzer
    from hit_astocker.analyzers.sentiment import SentimentAnalyzer
    from hit_astocker.analyzers.stock_sentiment import StockSentimentAnalyzer
    from hit_astocker.repositories.hsgt_repo import HsgtTop10Repository

    # Phase 1: independent analyzers
    sentiment = SentimentAnalyzer(conn, settings).analyze(trade_date)
    firstboard = FirstBoardAnalyzer(conn, settings).analyze(trade_date)
    lianban = LianbanAnalyzer(conn).analyze(trade_date)
    sector = SectorRotationAnalyzer(conn).analyze(trade_date)
    dragon = DragonTigerAnalyzer(conn).analyze(trade_date)
    event = EventClassifier(conn).analyze(trade_date)
    survival_model = BoardSurvivalAnalyzer(conn).compute_model(trade_date)
    hsgt_net_map = HsgtTop10Repository(conn).find_net_buyers_by_date(trade_date)

    # Phase 2: dependent analyzers for ALL potential signal candidates
    # (firstboard + lianban + theme leaders)
    fb_codes = {fb.ts_code for fb in firstboard}
    lianban_codes = set()
    for tier in lianban.tiers:
        for code in tier.stocks:
            lianban_codes.add(code)
    leader_codes = set()
    for th in event.theme_heats:
        for code in th.leader_codes:
            leader_codes.add(code)
    candidate_codes = list(fb_codes | lianban_codes | leader_codes)
    moneyflow = MoneyFlowAnalyzer(conn).analyze(trade_date, candidate_codes)
    stock_sentiments = StockSentimentAnalyzer(conn).analyze(trade_date, candidate_codes)

    return DailyAnalysisContext(
        trade_date=trade_date,
        sentiment=sentiment,
        firstboard=tuple(firstboard),
        lianban=lianban,
        sector=sector,
        dragon=dragon,
        event=event,
        survival_model=survival_model,
        hsgt_net_map=hsgt_net_map,
        moneyflow=tuple(moneyflow),
        stock_sentiments=tuple(stock_sentiments),
    )

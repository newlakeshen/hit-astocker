"""DailyAnalysisContext — 当日全量分析结果的不可变容器.

一次构建，多处复用（dashboard / signal / backtest），避免重复计算。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from hit_astocker.analyzers.board_survival import SurvivalModel
from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult, MoneyFlowResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult, StockSentimentScore
from hit_astocker.models.sector import SectorRotationResult
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import SentimentCycle


@dataclass(frozen=True)
class DataCoverage:
    """Tracks which factor data sources have real backing data.

    When a backing table is empty (not synced), the corresponding factor
    should be excluded from weighted scoring — not defaulted to 45/50.
    """

    has_ths_hot: bool = False       # ths_hot (同花顺热股 → popularity factor)
    has_hsgt: bool = False          # hsgt_top10 (北向资金 → northbound factor)
    has_stk_factor: bool = False    # stk_factor_pro (技术因子 → technical_form)
    has_hm: bool = False            # hm_detail (游资席位 → dragon_tiger boost)
    has_auction: bool = False       # stk_auction (竞价 → sentiment auction factor)

    @property
    def missing_sources(self) -> list[str]:
        """Return human-readable names of data sources with no data."""
        names = []
        if not self.has_ths_hot:
            names.append("ths_hot (同花顺热股)")
        if not self.has_hsgt:
            names.append("hsgt_top10 (北向资金)")
        if not self.has_stk_factor:
            names.append("stk_factor_pro (技术因子)")
        if not self.has_hm:
            names.append("hm_detail (游资席位)")
        if not self.has_auction:
            names.append("stk_auction (集合竞价)")
        return names

    @property
    def active_count(self) -> int:
        return sum([
            self.has_ths_hot,
            self.has_hsgt,
            self.has_stk_factor,
            self.has_hm,
            self.has_auction,
        ])

    @property
    def total_count(self) -> int:
        return 5


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
    coverage: DataCoverage = field(default_factory=DataCoverage)
    sentiment_cycle: SentimentCycle | None = None


@dataclass
class DailyContextCaches:
    """Reusable caches for multi-day context building."""

    survival_models: dict[tuple[date, int], SurvivalModel] = field(default_factory=dict)


def table_has_data(conn: sqlite3.Connection, table: str) -> bool:
    """Check if a table exists and has at least one row."""
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            return False
        row = conn.execute(f"SELECT 1 FROM [{table}] LIMIT 1").fetchone()  # noqa: S608
        return row is not None
    except sqlite3.OperationalError:
        return False


def table_has_data_for_date(
    conn: sqlite3.Connection,
    table: str,
    trade_date: date,
    *,
    date_column: str = "trade_date",
) -> bool:
    """Check whether a table has at least one row for a specific trading date."""
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            return False
        row = conn.execute(
            f"SELECT 1 FROM [{table}] WHERE [{date_column}] = ? LIMIT 1",  # noqa: S608
            (trade_date.strftime("%Y%m%d"),),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def build_daily_context(
    conn: sqlite3.Connection,
    settings,
    trade_date: date,
    *,
    llm_client=None,
    llm_cache=None,
    caches: DailyContextCaches | None = None,
) -> DailyAnalysisContext:
    """Run all analyzers once and return an immutable context.

    Parameters
    ----------
    conn : sqlite3.Connection
    settings : hit_astocker.config.settings.Settings
    trade_date : date
    llm_client : optional LLM client for event classification enhancement
    llm_cache : optional LLM response cache
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

    # ── Data coverage detection (one-time O(1) checks) ──
    coverage = DataCoverage(
        has_ths_hot=table_has_data_for_date(conn, "ths_hot", trade_date),
        has_hsgt=table_has_data_for_date(conn, "hsgt_top10", trade_date),
        has_stk_factor=table_has_data_for_date(conn, "stk_factor_pro", trade_date),
        has_hm=table_has_data_for_date(conn, "hm_detail", trade_date),
        has_auction=table_has_data_for_date(conn, "stk_auction", trade_date),
    )

    # Phase 1: independent analyzers (+ cycle detection)
    sentiment = SentimentAnalyzer(conn, settings).analyze(trade_date)

    from hit_astocker.analyzers.sentiment_cycle import SentimentCycleDetector
    try:
        sentiment_cycle = SentimentCycleDetector(conn).detect(trade_date, sentiment)
    except Exception:
        logging.getLogger(__name__).warning(
            "SentimentCycleDetector failed for %s", trade_date, exc_info=True,
        )
        sentiment_cycle = None
    firstboard = FirstBoardAnalyzer(conn, settings).analyze(trade_date)
    lianban = LianbanAnalyzer(conn).analyze(trade_date)
    sector = SectorRotationAnalyzer(conn).analyze(trade_date)
    dragon = DragonTigerAnalyzer(conn).analyze(trade_date)
    event = EventClassifier(conn, llm_client=llm_client, llm_cache=llm_cache).analyze(trade_date)
    lookback_years = getattr(settings, "survival_lookback_years", 6)
    survival_key = (trade_date, lookback_years)
    survival_model = caches.survival_models.get(survival_key) if caches else None
    if survival_model is None:
        survival_model = BoardSurvivalAnalyzer(conn).compute_model(
            trade_date, lookback_years=lookback_years,
        )
        if caches is not None:
            caches.survival_models[survival_key] = survival_model
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
    stock_sentiments = StockSentimentAnalyzer(conn).analyze(
        trade_date, candidate_codes, coverage=coverage, event_result=event,
    )

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
        coverage=coverage,
        sentiment_cycle=sentiment_cycle,
    )

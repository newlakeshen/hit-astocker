"""DailyAnalysisContext — 当日全量分析结果的不可变容器.

一次构建，多处复用（dashboard / signal / backtest），避免重复计算。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

from hit_astocker.analyzers.board_survival import SurvivalModel
from hit_astocker.models.analysis_result import FirstBoardResult, LianbanResult, MoneyFlowResult
from hit_astocker.models.dragon_tiger import DragonTigerResult
from hit_astocker.models.event_data import EventAnalysisResult, StockSentimentScore
from hit_astocker.models.profit_effect import ProfitEffectSnapshot
from hit_astocker.models.sector import SectorRotationResult
from hit_astocker.models.sentiment import SentimentScore
from hit_astocker.models.sentiment_cycle import SentimentCycle

if TYPE_CHECKING:
    from hit_astocker.repositories.hm_repo import HmRepository
    from hit_astocker.repositories.kpl_repo import KplRepository
    from hit_astocker.repositories.limit_repo import LimitListRepository
    from hit_astocker.repositories.limit_step_repo import LimitStepRepository


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
    profit_effect: ProfitEffectSnapshot | None = None


@dataclass
class DailyContextCaches:
    """Reusable caches for multi-day context building.

    Performance fields (populated before training loop):
    - limit_repo / step_repo / kpl_repo: shared pre-loaded repo instances
    - coverage_cache: per-day data coverage (batch pre-populated)
    - light_metrics_cache: SentimentCycleDetector lookback metrics (3/4 overlap)
    - concept_members_cache: concept membership (structural, rarely changes)
    """

    survival_models: dict[tuple[date, int], SurvivalModel] = field(default_factory=dict)
    coverage_cache: dict[date, DataCoverage] = field(default_factory=dict)

    # ── Training performance caches ──
    limit_repo: LimitListRepository | None = None
    step_repo: LimitStepRepository | None = None
    kpl_repo: KplRepository | None = None
    hm_repo: HmRepository | None = None
    light_metrics_cache: dict[date, Any] = field(default_factory=dict)
    concept_members_cache: dict[str, list[str]] = field(default_factory=dict)


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


def table_has_data_for_date_batch(
    conn: sqlite3.Connection,
    table: str,
    dates: list[date],
    *,
    date_column: str = "trade_date",
) -> set[date]:
    """Batch-check which dates have data in a table.

    Returns a set of dates that have at least one row.
    Single SQL query (SELECT DISTINCT) — O(1) round-trips vs O(N) for per-date checks.
    """
    if not dates:
        return set()
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            return set()
        date_strs = [d.strftime("%Y%m%d") for d in dates]
        placeholders = ",".join("?" * len(date_strs))
        rows = conn.execute(
            f"SELECT DISTINCT [{date_column}] FROM [{table}] "  # noqa: S608
            f"WHERE [{date_column}] IN ({placeholders})",
            date_strs,
        ).fetchall()
        db_dates_str = {r[0] for r in rows}
        return {d for d in dates if d.strftime("%Y%m%d") in db_dates_str}
    except sqlite3.OperationalError:
        return set()


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
    from hit_astocker.repositories.kpl_repo import KplRepository as _KplRepo
    from hit_astocker.repositories.limit_repo import LimitListRepository as _LimitRepo
    from hit_astocker.repositories.limit_step_repo import LimitStepRepository as _StepRepo

    # ── Shared repos (use pre-loaded when available) ──
    limit_repo = caches.limit_repo if caches and caches.limit_repo else _LimitRepo(conn)
    step_repo = caches.step_repo if caches and caches.step_repo else _StepRepo(conn)
    kpl_repo = caches.kpl_repo if caches and caches.kpl_repo else _KplRepo(conn)

    # ── Data coverage detection (per-day, not table-level) ──
    # coverage_cache is pre-populated in batch by backtest/train commands
    if caches and trade_date in caches.coverage_cache:
        coverage = caches.coverage_cache[trade_date]
    else:
        coverage = DataCoverage(
            has_ths_hot=table_has_data_for_date(conn, "ths_hot", trade_date),
            has_hsgt=table_has_data_for_date(conn, "hsgt_top10", trade_date),
            has_stk_factor=table_has_data_for_date(conn, "stk_factor_pro", trade_date),
            has_hm=table_has_data_for_date(conn, "hm_detail", trade_date),
            has_auction=table_has_data_for_date(conn, "stk_auction", trade_date),
        )
        if caches is not None:
            caches.coverage_cache[trade_date] = coverage

    # Phase 1: independent analyzers (+ cycle detection + profit effect)
    sentiment = SentimentAnalyzer(
        conn, settings, limit_repo=limit_repo, step_repo=step_repo,
    ).analyze(trade_date)

    from hit_astocker.analyzers.sentiment_cycle import SentimentCycleDetector
    try:
        _metrics_cache = caches.light_metrics_cache if caches else None
        sentiment_cycle = SentimentCycleDetector(
            conn, limit_repo=limit_repo, step_repo=step_repo,
        ).detect(trade_date, sentiment, light_metrics_cache=_metrics_cache)
    except Exception:
        logging.getLogger(__name__).warning(
            "SentimentCycleDetector failed for %s", trade_date, exc_info=True,
        )
        sentiment_cycle = None

    from hit_astocker.analyzers.profit_effect import ProfitEffectAnalyzer
    try:
        profit_effect = ProfitEffectAnalyzer(conn).analyze(trade_date)
    except Exception:
        logging.getLogger(__name__).warning(
            "ProfitEffectAnalyzer failed for %s", trade_date, exc_info=True,
        )
        profit_effect = None
    firstboard = FirstBoardAnalyzer(
        conn, settings, limit_repo=limit_repo, kpl_repo=kpl_repo,
    ).analyze(trade_date)
    lianban = LianbanAnalyzer(conn, step_repo=step_repo).analyze(trade_date)
    sector = SectorRotationAnalyzer(conn).analyze(trade_date)
    _hm_repo = caches.hm_repo if caches and caches.hm_repo else None
    dragon = DragonTigerAnalyzer(conn, hm_repo=_hm_repo).analyze(trade_date)
    _concept_cache = caches.concept_members_cache if caches else None
    event = EventClassifier(
        conn, llm_client=llm_client, llm_cache=llm_cache,
        limit_repo=limit_repo, step_repo=step_repo, kpl_repo=kpl_repo,
        concept_members_cache=_concept_cache,
    ).analyze(trade_date)
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
        profit_effect=profit_effect,
    )

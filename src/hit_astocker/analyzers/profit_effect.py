"""赚钱效应分层分析器 — 按板高度×涨跌幅类型量化打板赚钱效应.

数据流:
  1. T-1 的涨停股 (limit_list_d limit='U') + 高度 (limit_step)
  2. T 的 OHLCV (daily_bar) → 计算溢价/收益/胜率
  3. T 的涨停/炸板 (limit_list_d) → 计算炸板率/非一字率
  4. 按 height tier × 10cm/20cm 分组聚合
  5. 基于分层指标判定 regime (STRONG/NORMAL/WEAK/FROZEN)

性能: 3 次 SQL + 1 次 batch query, 无 N+1.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from hit_astocker.config.constants import TUSHARE_DATE_FMT
from hit_astocker.models.profit_effect import (
    ProfitEffectSnapshot,
    ProfitRegime,
    TierProfitEffect,
    _height_to_tier,
)
from hit_astocker.repositories.daily_bar_repo import DailyBarRepository
from hit_astocker.utils.date_utils import get_previous_trading_day

logger = logging.getLogger(__name__)


def _is_20cm(ts_code: str) -> bool:
    """判断股票是否为 20cm 涨跌幅类型 (创业板 30 / 科创板 68)."""
    return ts_code[:2] in ("30", "68")


@dataclass
class _StockRecord:
    """内部中间数据: 单只股票的昨日+今日数据."""

    ts_code: str
    prev_close: float
    height: int
    is_20cm: bool
    today_open: float | None = None
    today_close: float | None = None


@dataclass
class _TodayBoardRecord:
    """内部中间数据: 今日的涨停/炸板记录."""

    ts_code: str
    limit_type: str     # 'U' or 'Z'
    open_times: int
    first_time: str
    height: int
    is_20cm: bool


class ProfitEffectAnalyzer:
    """赚钱效应分层分析器."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._bar_repo = DailyBarRepository(conn)

    def analyze(self, trade_date: date) -> ProfitEffectSnapshot | None:
        """计算当日赚钱效应分层快照.

        Returns None if no previous trading day or no limit-up data.
        """
        prev_date = get_previous_trading_day(trade_date)
        if prev_date is None:
            return None

        # Step 1: 获取 T-1 涨停股 + 高度
        prev_stocks = self._get_prev_limit_ups(prev_date)
        if not prev_stocks:
            return None

        # Step 2: 批量获取 T 的 OHLCV
        codes = [s.ts_code for s in prev_stocks]
        today_bars = self._bar_repo.find_recent_bars_batch(codes, trade_date, count=1)
        for stock in prev_stocks:
            bars = today_bars.get(stock.ts_code, [])
            if bars and bars[-1].trade_date == trade_date:
                stock.today_open = bars[-1].open
                stock.today_close = bars[-1].close

        # Step 3: 获取 T 的涨停/炸板记录 (用于质量指标)
        today_boards = self._get_today_boards(trade_date)

        # Step 4: 分层聚合
        by_height = self._aggregate_tiers(prev_stocks, today_boards, filter_fn=None)
        by_height_10cm = self._aggregate_tiers(
            prev_stocks, today_boards, filter_fn=lambda s: not s.is_20cm,
        )
        by_height_20cm = self._aggregate_tiers(
            prev_stocks, today_boards, filter_fn=lambda s: s.is_20cm,
        )

        # Step 5: 总体指标
        premiums, returns = [], []
        for s in prev_stocks:
            if s.today_open is not None and s.prev_close > 0:
                premiums.append((s.today_open - s.prev_close) / s.prev_close * 100)
            if s.today_close is not None and s.prev_close > 0:
                returns.append((s.today_close - s.prev_close) / s.prev_close * 100)

        overall_premium = sum(premiums) / len(premiums) if premiums else 0.0
        overall_win_rate = (
            sum(1 for r in returns if r > 0) / len(returns) if returns else 0.0
        )

        # Step 6: Regime 判定
        regime_score = self._compute_regime_score(
            overall_premium, overall_win_rate, by_height, today_boards,
        )
        regime = _classify_regime(regime_score)

        return ProfitEffectSnapshot(
            trade_date=trade_date,
            by_height=tuple(by_height),
            by_height_10cm=tuple(by_height_10cm),
            by_height_20cm=tuple(by_height_20cm),
            overall_premium=round(overall_premium, 2),
            overall_win_rate=round(overall_win_rate, 4),
            overall_count=len(prev_stocks),
            regime=regime,
            regime_score=round(regime_score, 2),
        )

    # ── 数据获取 ──

    def _get_prev_limit_ups(self, prev_date: date) -> list[_StockRecord]:
        """获取 T-1 涨停股 + 高度 (LEFT JOIN limit_step)."""
        date_str = prev_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT
                l.ts_code,
                l."close" as prev_close,
                COALESCE(s.nums, 1) as height
            FROM limit_list_d l
            LEFT JOIN limit_step s
                ON l.ts_code = s.ts_code AND l.trade_date = s.trade_date
            WHERE l.trade_date = ? AND l."limit" = 'U'
              AND l.name NOT LIKE '%ST%'
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return [
            _StockRecord(
                ts_code=r["ts_code"],
                prev_close=r["prev_close"] or 0.0,
                height=r["height"],
                is_20cm=_is_20cm(r["ts_code"]),
            )
            for r in rows
        ]

    def _get_today_boards(self, trade_date: date) -> list[_TodayBoardRecord]:
        """获取 T 的涨停/炸板记录 + 高度."""
        date_str = trade_date.strftime(TUSHARE_DATE_FMT)
        sql = """
            SELECT
                l.ts_code,
                l."limit" as limit_type,
                l.open_times,
                l.first_time,
                COALESCE(s.nums, 1) as height
            FROM limit_list_d l
            LEFT JOIN limit_step s
                ON l.ts_code = s.ts_code AND l.trade_date = s.trade_date
            WHERE l.trade_date = ? AND l."limit" IN ('U', 'Z')
              AND l.name NOT LIKE '%ST%'
        """
        rows = self._conn.execute(sql, (date_str,)).fetchall()
        return [
            _TodayBoardRecord(
                ts_code=r["ts_code"],
                limit_type=r["limit_type"],
                open_times=r["open_times"] or 0,
                first_time=r["first_time"] or "",
                height=r["height"],
                is_20cm=_is_20cm(r["ts_code"]),
            )
            for r in rows
        ]

    # ── 分层聚合 ──

    @staticmethod
    def _aggregate_tiers(
        prev_stocks: list[_StockRecord],
        today_boards: list[_TodayBoardRecord],
        *,
        filter_fn=None,
    ) -> list[TierProfitEffect]:
        """按 height tier 聚合赚钱效应指标.

        filter_fn: 可选过滤函数, 用于 10cm/20cm 分层.
        """
        # ── T-1 continuation metrics (按 tier 分组) ──
        tier_premiums: dict[str, list[float]] = defaultdict(list)
        tier_returns: dict[str, list[float]] = defaultdict(list)
        tier_prev_count: dict[str, int] = defaultdict(int)

        for s in prev_stocks:
            if filter_fn is not None and not filter_fn(s):
                continue
            tier = _height_to_tier(s.height)
            tier_prev_count[tier] += 1
            if s.today_open is not None and s.prev_close > 0:
                tier_premiums[tier].append(
                    (s.today_open - s.prev_close) / s.prev_close * 100,
                )
            if s.today_close is not None and s.prev_close > 0:
                tier_returns[tier].append(
                    (s.today_close - s.prev_close) / s.prev_close * 100,
                )

        # ── T board quality metrics (按 tier 分组) ──
        tier_up: dict[str, int] = defaultdict(int)
        tier_broken: dict[str, int] = defaultdict(int)
        tier_non_yizi: dict[str, int] = defaultdict(int)

        for b in today_boards:
            if filter_fn is not None:
                # 对 today_boards 使用 is_20cm 做过滤
                mock = _StockRecord(
                    ts_code=b.ts_code, prev_close=0, height=0, is_20cm=b.is_20cm,
                )
                if not filter_fn(mock):
                    continue
            tier = _height_to_tier(b.height)
            if b.limit_type == "U":
                tier_up[tier] += 1
                # 非一字: open_times > 0 或 first_time > "09:25"
                if b.open_times > 0 or (b.first_time and b.first_time > "09:25"):
                    tier_non_yizi[tier] += 1
            elif b.limit_type == "Z":
                tier_broken[tier] += 1

        # ── 合并生成 TierProfitEffect ──
        all_tiers = sorted(
            set(tier_prev_count.keys())
            | set(tier_up.keys())
            | set(tier_broken.keys()),
            key=lambda t: _tier_sort_key(t),
        )

        result = []
        for tier in all_tiers:
            pc = tier_prev_count.get(tier, 0)
            prems = tier_premiums.get(tier, [])
            rets = tier_returns.get(tier, [])
            up = tier_up.get(tier, 0)
            broken = tier_broken.get(tier, 0)
            non_yizi = tier_non_yizi.get(tier, 0)
            today_total = up + broken

            result.append(TierProfitEffect(
                tier=tier,
                prev_count=pc,
                avg_premium=round(sum(prems) / len(prems), 2) if prems else 0.0,
                avg_return=round(sum(rets) / len(rets), 2) if rets else 0.0,
                win_rate=round(
                    sum(1 for r in rets if r > 0) / len(rets), 4,
                ) if rets else 0.0,
                today_count=today_total,
                broken_rate=round(
                    broken / today_total, 4,
                ) if today_total > 0 else 0.0,
                non_yizi_rate=round(non_yizi / up, 4) if up > 0 else 0.0,
            ))

        return result

    # ── Regime 判定 ──

    @staticmethod
    def _compute_regime_score(
        overall_premium: float,
        overall_win_rate: float,
        by_height: list[TierProfitEffect],
        today_boards: list[_TodayBoardRecord],
    ) -> float:
        """计算 regime_score (0-100).

        权重分配:
        - 40%: 总体溢价 ([-3%, +5%] → [0, 100])
        - 30%: 总体胜率 (0-1 → 0-100)
        - 15%: 正溢价层占比 (鼓励多层赚钱)
        - 15%: 总体非炸板率 (100 - broken_rate * 100)
        """
        # 溢价分 (40%)
        premium_score = max(0, min(100, (overall_premium + 3) / 8 * 100))

        # 胜率分 (30%)
        winrate_score = overall_win_rate * 100

        # 正溢价层占比 (15%)
        if by_height:
            positive_tiers = sum(
                1 for t in by_height if t.avg_premium > 0 and t.prev_count >= 2
            )
            tier_breadth = positive_tiers / len(by_height) * 100
        else:
            tier_breadth = 0

        # 非炸板率 (15%)
        total_up = sum(1 for b in today_boards if b.limit_type == "U")
        total_broken = sum(1 for b in today_boards if b.limit_type == "Z")
        total_board = total_up + total_broken
        non_broken_score = (
            (1 - total_broken / total_board) * 100 if total_board > 0 else 50
        )

        return (
            premium_score * 0.40
            + winrate_score * 0.30
            + tier_breadth * 0.15
            + non_broken_score * 0.15
        )


def _classify_regime(score: float) -> ProfitRegime:
    """将 regime_score 映射到 ProfitRegime 枚举."""
    if score >= 65:
        return ProfitRegime.STRONG
    if score >= 45:
        return ProfitRegime.NORMAL
    if score >= 25:
        return ProfitRegime.WEAK
    return ProfitRegime.FROZEN


_TIER_ORDER = {"首板": 0, "2板": 1, "3板": 2, "空间板": 3}


def _tier_sort_key(tier: str) -> int:
    return _TIER_ORDER.get(tier, 99)
